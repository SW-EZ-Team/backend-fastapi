"""로컬 Mac용 SenseVoice-Small (MLX) 커넥터.

Blaizzy/mlx-audio 의 stt.models.sensevoice 구현체를 얇게 감싼다.
Qwen3-ASR / Whisper Turbo 커넥터와 동일한 Protocol 시그니처 + 싱글톤 lazy load +
오디오 정규화 패턴을 그대로 따른다.

mlx-audio API 형태는 Qwen3-ASR 의 Session 방식에 가깝다 —
`mlx_audio.stt.utils.load(repo)` 가 반환하는 nn.Module 인스턴스를 보관하고,
`model.generate(audio, language=..., use_itn=...)` 을 호출해 STTOutput 을 얻는다.
따라서 Whisper Turbo 의 함수형 warmup 패턴이 아니라 Qwen3-ASR 의 session 패턴을 택한다.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from common.audio_io import duration_sec, load_audio_from_bytes
from common.config import get_sensevoice_model_path
from common.logging import get_logger

from ..errors import InferenceError, ModelLoadError
from ..schemas import ASRRequest, ASRResponse

_LOG = get_logger(__name__)

# SenseVoice 내부 frontend_conf.fs 와 동일 — 16kHz mono 입력 요구
_TARGET_SR = 16000

# language=auto 신호 — SenseVoice 의 LID(Language Identification) 가 인코더 내부에서 처리
_AUTO_LANG_TOKEN = "auto"

# SenseVoice 가 공식적으로 받아들이는 언어 코드 집합 — auto / zh / en / yue / ja / ko / nospeech
# 샌드박스가 요구하는 ko/en/ja/zh/auto 는 모두 이 집합의 부분집합이다.
_SUPPORTED_LANGS: frozenset[str] = frozenset(
    {"auto", "zh", "en", "yue", "ja", "ko", "nospeech"}
)


class SenseVoiceSmallConnector:
    """SenseVoice-Small(234M) MLX 변환본을 로컬 Mac 에서 실행하는 커넥터.

    mlx-community/SenseVoiceSmall (mlx-audio 0.4.0 으로 변환된 936MB quantized)
    를 기본 모델로 쓴다. 싱글톤은 프로세스당 한 번만 load() 호출해 nn.Module
    인스턴스를 보관한다. FastAPI 워커별 개별 로드지만 단일 uvicorn 프로세스 기준 안전.

    SenseVoice 는 NAR 인코더-only 구조라 10초 오디오를 ~70ms 안에 처리한다
    (공개 스펙 기준). Whisper 의 30초 prefix 자동 감지 대신 LID 가 내장돼
    언어 감지가 추론 한 번에 끝난다.
    """

    # 커넥터 식별자 — registry 키와 동일하게 유지
    name: str = "sensevoice-small"

    # 클래스 변수로 싱글톤 보관 — 타입은 mlx_audio.stt.models.sensevoice.SenseVoiceSmall
    _model: Any | None = None
    # Lock 은 첫 호출 시 생성 — 이벤트 루프 바인딩 시점 충돌 방지
    _load_lock: asyncio.Lock | None = None
    # 로드된 모델 경로 — .env 변경으로 경로가 바뀌면 재로드 트리거
    _model_path: str | None = None

    async def generate(self, request: ASRRequest) -> ASRResponse:
        """ASR 요청 → 트랜스크립트 응답.

        Qwen3-ASR 커넥터와 동일한 절차: 오디오 정규화 → 모델 준비 → 추론 → 응답 매핑.
        언어 코드는 SenseVoice 가 받아들이는 집합 안이면 그대로 전달, 아니면 'auto' 로 폴백.
        """
        # 1) 오디오 로드 + 정규화 (블로킹 IO 는 스레드로)
        audio, sr = await asyncio.to_thread(
            load_audio_from_bytes, request.audio_bytes, _TARGET_SR
        )
        audio_len = duration_sec(audio, sr)
        # 2) 모델 준비 (최초 1회만)
        model_path = get_sensevoice_model_path()
        model = await self._ensure_model(model_path)
        # 3) 언어 코드 정규화 — 지원 범위 밖이면 auto 로 폴백
        language = self._normalize_language(request.language)
        # 4) 실제 추론 + 지연시간 측정 (MLX 연산도 블로킹)
        t0 = time.perf_counter()
        try:
            result = await asyncio.to_thread(
                model.generate,
                audio,
                language=language,
                use_itn=False,
            )
        except (RuntimeError, ValueError, KeyError) as exc:
            # mlx-audio SenseVoice 가 던지는 예외는 주로 shape/device/token 오류.
            # 공통 예외 인터페이스(InferenceError) 로 정규화한다.
            # 이 패턴은 errors.py 의 설계 원칙("벤더 예외 → 공통형 번역") 그대로다.
            _LOG.exception("sensevoice-small 추론 실패")
            raise InferenceError(f"ASR inference failed: {exc}") from exc
        latency_ms = (time.perf_counter() - t0) * 1000.0
        # 5) 응답 스키마로 정규화 — STTOutput.text / .language 를 ASRResponse 에 매핑
        detected_lang = getattr(result, "language", None) or language
        return ASRResponse(
            text=str(getattr(result, "text", "") or "").strip(),
            language=str(detected_lang),
            duration_sec=audio_len,
            latency_ms=latency_ms,
            model=self.name,
        )

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그.

        - basic / transcription: 기본 음성→텍스트 변환
        - language_override / language_hint: ko/en/ja/zh/auto 등 언어 코드 명시 가능
        - emotion_detection: SenseVoice 내장 SER (happy/sad/angry/neutral)
        - event_detection: 내장 AED (웃음/박수/기침/BGM)
        - language_detection: 내장 LID (language=auto 시 인코더가 감지)
        """
        return feature in {
            "basic",
            "transcription",
            "language_override",
            "language_hint",
            "emotion_detection",
            "event_detection",
            "language_detection",
        }

    @classmethod
    async def _ensure_model(cls, model_path: str) -> Any:
        """모델 싱글톤 생성 — 동시 접근은 Lock 으로 직렬화한다.

        경로가 바뀌면(.env 갱신) 재로드한다. mlx-audio 가 내부 캐시를 보관하므로
        두 번째 이후 로드는 HF 캐시 hit 라 저비용이다.
        """
        # 빠른 경로 — 같은 경로로 이미 로드됐으면 락 없이 반환
        if cls._model is not None and cls._model_path == model_path:
            return cls._model
        # Lock 지연 생성 — 현재 이벤트 루프에 바인딩
        if cls._load_lock is None:
            cls._load_lock = asyncio.Lock()
        async with cls._load_lock:
            # 락 획득 후 재확인 — 대기 중 다른 요청이 로드했을 수 있음
            if cls._model is not None and cls._model_path == model_path:
                return cls._model
            cls._model = await asyncio.to_thread(cls._build_model, model_path)
            cls._model_path = model_path
            return cls._model

    @classmethod
    def _build_model(cls, model_path: str) -> Any:
        """mlx_audio.stt.utils.load() 호출. 실패 시 ModelLoadError 로 래핑."""
        # lazy import — 모듈 import 시점에 MLX 디바이스 초기화가 일어나지 않도록
        try:
            from mlx_audio.stt.utils import load
        except ImportError as exc:
            raise ModelLoadError(
                "mlx-audio 라이브러리가 설치되어 있지 않음. "
                "`uv pip install mlx-audio==0.4.2` 실행 필요"
            ) from exc
        _LOG.info("SenseVoice-Small 모델 로드 시작: %s", model_path)
        try:
            model = load(model_path)
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            # 로드 실패 원인은 다양 — safetensors 역직렬화, HF 다운로드 실패,
            # BPE 토크나이저 누락 등. 구체 원인을 메시지로 전달하되 타입은 통일한다.
            raise ModelLoadError(
                f"SenseVoice-Small 모델 로드 실패 (path={model_path}): {exc}"
            ) from exc
        _LOG.info("SenseVoice-Small 모델 로드 완료")
        return model

    @staticmethod
    def _normalize_language(language: str | None) -> str:
        """요청 언어 코드를 SenseVoice 가 받아들이는 집합으로 정규화한다.

        - None / 빈 문자열 / 미지원 코드 → 'auto' 로 폴백 (LID 가 알아서 감지)
        - 대소문자 차이는 lower() 로 흡수
        """
        if not language:
            return _AUTO_LANG_TOKEN
        normalized = language.strip().lower()
        if normalized in _SUPPORTED_LANGS:
            return normalized
        # 지원 범위 밖(예: ru/es 등) → auto 로 돌려서 거절하지 않고 추론 시도
        return _AUTO_LANG_TOKEN
