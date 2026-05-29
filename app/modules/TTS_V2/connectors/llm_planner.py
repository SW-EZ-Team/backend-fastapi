"""TTS V2 — Qwen3-4B 기반 낭독 텍스트 재작성 커넥터.

오디오북 TTS 합성 전, normalized_text 를 낭독하기 쉬운 형태로 변환한다.
로컬 Mac: MLX 4bit 양자화 Qwen3-4B-Instruct-2507 (MPS 네이티브 실행).
배포 Modal: 원본 가중치 모델로 교체 — .env TTS_V2_LLM_PLANNER_MODEL_PATH 한 줄 수정.

SRP: 이 파일은 Manager 레벨 (모델 생명주기 + 낭독 재작성 조합).
 - 프롬프트 빌드: _build_system_prompt / _build_messages
 - 추론 실행: _run_generate
 - 토큰 수 계산: _resolve_max_tokens
"""
from __future__ import annotations

import logging
import threading

_LOG = logging.getLogger(__name__)

# 낭독 재작성 시 입력 대비 출력 토큰 예측 배율.
# 재작성은 의미를 바꾸지 않아 원문과 길이가 비슷하므로 2배 + 고정 버퍼면 안전.
_MAX_TOKENS_RATIO = 2
_MAX_TOKENS_BUFFER = 64
_MAX_TOKENS_CEIL = 1024

# 10자 미만 입력은 LLM 추론 없이 원문 반환 — 프롬프트 overhead 대비 가치 없음.
_SKIP_LEN_THRESHOLD = 10

# 낭독 재작성용 시스템 프롬프트 — probe 검증 전 초안.
_SYSTEM_PROMPT_KO = (
    "당신은 오디오북 낭독자를 위한 텍스트 전처리 전문가입니다.\n"
    "주어진 텍스트를 낭독하기 쉬운 형태로 변환해주세요.\n\n"
    "규칙:\n"
    "1. 원문의 의미를 절대 변경하지 마세요.\n"
    "2. 쉼표와 마침표를 자연스러운 호흡 위치에 넣어주세요.\n"
    "3. 수식, 기호, 약어는 말로 풀어서 표현해주세요 "
    "(예: \"3x + 2\" → \"삼 엑스 더하기 이\").\n"
    "4. 60자 이상의 긴 문장은 의미 단위로 나눠주세요.\n"
    "5. 원문의 톤(존댓말/반말)을 그대로 유지하세요.\n"
    "6. 결과만 출력하세요. 설명이나 주석은 붙이지 마세요."
)


def _build_messages(text: str, language: str) -> list[dict[str, str]]:
    """Kanana chat template 용 메시지 배열을 반환한다.

    language 가 'ko' 이외이면 한국어 규칙 프롬프트를 그대로 쓴다
    (현재 지원 언어가 한국어뿐이므로 추후 확장 시 분기 추가).
    """
    _ = language  # 향후 다국어 분기 확장 위한 파라미터 유지
    return [
        {"role": "system", "content": _SYSTEM_PROMPT_KO},
        {"role": "user", "content": text},
    ]


def _resolve_max_tokens(text: str) -> int:
    """입력 길이 기반으로 최대 생성 토큰 수를 결정한다.

    재작성 결과는 원문과 비슷한 길이이므로 2배 + 버퍼면 충분하다.
    1024 토큰 상한으로 과다 생성을 방지한다.
    """
    estimated = len(text) * _MAX_TOKENS_RATIO + _MAX_TOKENS_BUFFER
    return min(estimated, _MAX_TOKENS_CEIL)


def _run_generate(model: object, tokenizer: object, prompt_text: str, max_tokens: int) -> str:
    """mlx_lm.generate 블로킹 호출을 감싼 아톰 함수.

    mlx_lm 0.31.3 부터 temp/top_k/top_p 를 generate() 에 직접 전달할 수 없다.
    make_sampler 로 sampler 객체를 먼저 만든 뒤 sampler= 키워드로 전달해야 한다.
    temperature=0.3 으로 충실한 재작성을 유도하되 너무 greedy 하지 않게 한다.
    """
    from mlx_lm import generate  # lazy import — Metal 초기화 지연
    from mlx_lm.generate import make_sampler  # 0.31.3+ 필수 샘플러 팩토리

    sampler = make_sampler(temp=0.3, top_k=50, top_p=1.0)
    return generate(
        model,
        tokenizer,
        prompt=prompt_text,
        max_tokens=max_tokens,
        sampler=sampler,
        verbose=False,
    )


class ReadingPlanner:
    """Qwen3-4B-Instruct MLX 기반 낭독 텍스트 재작성기.

    모델 로드는 프로세스 당 1회 (싱글톤). threading.Lock 으로 중복 로드를 방지한다.
    mlx_lm 미설치 또는 모델 로드 실패 시 자동으로 identity fallback 으로 전환한다.
    """

    _model: object = None
    _tokenizer: object = None
    _load_lock: threading.Lock | None = None
    _unavailable: bool = False  # 한 번 실패하면 재시도하지 않는다

    @classmethod
    def load_model(cls) -> None:
        """Qwen3-4B MLX 모델을 싱글톤으로 로드한다.

        이미 로드되어 있거나 불가 상태이면 즉시 반환한다.
        """
        if cls._model is not None or cls._unavailable:
            return
        if cls._load_lock is None:
            cls._load_lock = threading.Lock()
        with cls._load_lock:
            # Double-check: 락 대기 중 다른 스레드가 먼저 로드했을 수 있다
            if cls._model is not None or cls._unavailable:
                return
            cls._do_load()

    @classmethod
    def _do_load(cls) -> None:
        """실제 mlx_lm.load 호출 — load_model 의 락 블록 안에서만 호출된다."""
        from app.modules.TTS_V2.pipeline.config import TTS_V2_LLM_PLANNER_MODEL_PATH

        model_id = TTS_V2_LLM_PLANNER_MODEL_PATH
        try:
            from mlx_lm import load as mlx_load  # lazy import

            model, tokenizer = mlx_load(model_id)
            cls._model = model
            cls._tokenizer = tokenizer
            _LOG.info("ReadingPlanner 모델 로드 완료: %s", model_id)
        except ImportError:
            _LOG.warning("mlx_lm 미설치 — ReadingPlanner identity fallback 사용")
            cls._unavailable = True
        except Exception as exc:
            _LOG.warning("ReadingPlanner 모델 로드 실패 (%s) — identity fallback: %s", model_id, exc)
            cls._unavailable = True

    @classmethod
    def unload_model(cls) -> None:
        """모델을 언로드하고 싱글톤을 초기화한다."""
        cls._model = None
        cls._tokenizer = None
        _LOG.info("ReadingPlanner 모델 언로드 완료")

    @classmethod
    def is_loaded(cls) -> bool:
        """모델이 메모리에 로드된 상태인지 반환한다."""
        return cls._model is not None and cls._tokenizer is not None

    @classmethod
    def rewrite_for_reading(cls, text: str, language: str = "ko") -> str:
        """텍스트를 낭독에 적합한 형태로 재작성한다.

        변환 원칙:
        1. 의미는 절대 변경하지 않는다
        2. 쉼표/마침표를 자연스러운 호흡 위치에 배치한다
        3. 수식·기호·약어를 발화형으로 변환한다
        4. 60자 초과 문장은 의미 단위로 분리한다
        5. 원문의 존댓말/반말 톤을 유지한다

        모델 미로드 / 추론 실패 시 원문을 그대로 반환한다 (identity fallback).
        """
        if len(text) < _SKIP_LEN_THRESHOLD:
            return text

        cls.load_model()

        if cls._unavailable or cls._model is None or cls._tokenizer is None:
            return text

        return cls._call_model(text, language)

    @classmethod
    def _call_model(cls, text: str, language: str) -> str:
        """모델 추론을 수행하고 결과를 반환한다. 실패 시 원문 반환."""
        try:
            messages = _build_messages(text, language)
            # tokenize=False 로 문자열을 반환받아야 mlx_lm.generate() 의 prompt= 에 전달 가능
            prompt_text = cls._tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=False,
            )
            max_tokens = _resolve_max_tokens(text)
            return _run_generate(cls._model, cls._tokenizer, prompt_text, max_tokens)
        except Exception as exc:
            _LOG.warning("ReadingPlanner 추론 실패 — identity fallback: %s", exc)
            return text
