"""환경 변수 기반 설정을 한 곳에서 관리한다."""
from __future__ import annotations

import os
from functools import cache
from pathlib import Path

from dotenv import load_dotenv


@cache
def _load_env() -> None:
    """환경 파일은 한 번만 로드한다."""
    module_env = Path(__file__).resolve().parents[1] / ".env"
    root_env = Path(__file__).resolve().parents[4] / ".env"
    load_dotenv(root_env)
    load_dotenv(module_env, override=True)


def _optional(key: str) -> str | None:
    """빈 문자열은 미설정으로 취급한다."""
    _load_env()
    value = os.environ.get(key)
    if value is None or value == "":
        return None
    return value


def _required(key: str) -> str:
    """필수 환경값이 없으면 즉시 실패한다."""
    value = _optional(key)
    if value is None:
        raise RuntimeError(f"{key}가 설정되지 않았다.")
    return value


def _int_env(key: str, default: int) -> int:
    """정수 환경 변수를 안전하게 파싱한다. 유효하지 않으면 기본값 사용."""
    raw = _optional(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        import logging
        logging.getLogger(__name__).warning(
            "%s='%s'는 유효한 정수가 아님 — 기본값 %d 사용", key, raw, default,
        )
        return default


def _bool_env(key: str, default: bool) -> bool:
    """불리언 환경 변수를 여러 표기 방식으로 읽는다."""
    raw = _optional(key)
    if raw is None:
        return default
    return raw.strip().lower() not in {"false", "0", "no", "off"}


def anthropic_api_key() -> str | None:
    """Anthropic API 키를 반환한다."""
    return _optional("ANTHROPIC_API_KEY")


def google_api_key() -> str | None:
    """Google AI Studio API 키를 반환한다. GEMINI_API_KEY를 대체 키로 허용한다."""
    return _optional("GOOGLE_API_KEY") or _optional("GEMINI_API_KEY")


def gemini_text_model() -> str:
    """google-genai 텍스트 커넥터의 모델 ID를 반환한다."""
    return _optional("GEMINI_TEXT_MODEL") or "gemini-3.5-flash"


def active_text_model() -> str:
    """텍스트 생성 커넥터 이름을 반환한다."""
    return _optional("ACTIVE_TEXT_MODEL") or "opus46"


def active_planner_model() -> str:
    """계획 수립 커넥터 이름을 반환한다."""
    return _optional("ACTIVE_PLANNER_MODEL") or "opus46"


def active_verifier_model() -> str:
    """검증용 커넥터 이름. 미설정이면 활성 텍스트 모델을 그대로 쓴다."""
    return _optional("ACTIVE_VERIFIER_MODEL") or active_text_model()


# <think> reasoning을 본문 토큰으로 소비하는 모델 이름 패턴.
# 이런 모델은 JSON 본문 외에 추론 토큰을 추가로 쓰므로 max_tokens 여유가 필요하다.
# codex_cli/claude 계열은 본문에 reasoning을 노출하지 않으므로 여기 포함하지 않는다.
_REASONING_MODEL_HINTS: tuple[str, ...] = ("qwen", "glm", "deepseek", "r1")


def is_reasoning_model(model_name: str) -> bool:
    """모델 이름이 reasoning(<think> 소비) 계열인지 휴리스틱으로 판별한다."""
    lowered = model_name.lower()
    return any(hint in lowered for hint in _REASONING_MODEL_HINTS)


def distractor_rewrite_enabled() -> bool:
    """오답(distractor) 재작성 노드의 활성화 여부를 명시 플래그로 결정한다.

    과거에는 connector.supports("cli") 휴리스틱으로 켜고 껐는데, 그러면 활성
    모델(gemini=cli지원=스킵, codex/anthropic=비cli=실행)에 따라 오답 재작성이
    조용히 켜지고 꺼지는 문제(감사 A-2)가 있었다. 이를 명시 환경 플래그로 정리한다.

    기본값은 활성화(true). 코드 헤비 보기로 JSON이 깨질 위험이 큰 환경 등에서
    EXAMFORGE_DISTRACTOR_REWRITE=false로 끄면 초기 생성 보기를 그대로 보존한다.
    """
    raw = _optional("EXAMFORGE_DISTRACTOR_REWRITE")
    if raw is None:
        return True
    return raw.strip().lower() not in {"false", "0", "no", "off"}


def targeted_repair_enabled() -> bool:
    """검증 실패 문항의 표적 교정(repair) 경로 활성화 여부.

    기본 활성화(true). 회귀가 의심되면 EXAMFORGE_TARGETED_REPAIR=false로 끄면
    retry가 곧바로 기존 blind 재생성으로 폴백해 변경 이전 동작과 동일해진다.
    """
    raw = _optional("EXAMFORGE_TARGETED_REPAIR")
    if raw is None:
        return True
    return raw.strip().lower() not in {"false", "0", "no", "off"}


def verification_advisory_enabled() -> bool:
    """신뢰 낮은 검증기에서는 검증 결과를 관측용으로만 사용한다."""
    if _bool_env("EXAMFORGE_VERIFICATION_ADVISORY", False):
        return True
    return active_verifier_model().strip().lower() == "codex_cli"


def verifier_max_tokens(base: int) -> int:
    """검증/교정 호출의 max_tokens를 활성 검증 모델에 맞게 보정한다.

    reasoning 모델이면 <think> 토큰 여유를 위해 base의 2배(최대 8000)를 주고,
    codex/claude 같은 비-reasoning 모델이면 base를 그대로 사용한다 — 이렇게 해야
    codex 경로의 토큰·비용이 불변으로 유지된다.
    """
    if is_reasoning_model(active_verifier_model()):
        return min(base * 2, 8000)
    return base


def max_retries() -> int:
    """파이프라인 최대 재시도 횟수."""
    return _int_env("MAX_RETRIES", 3)


def generation_concurrency() -> int:
    """문제 생성 병렬 상한. 0 이하 설정 시 데드락 방지를 위해 최소 1로 보정한다."""
    return max(1, _int_env("GENERATION_CONCURRENCY", 4))


def verification_concurrency() -> int:
    """정답 검증 병렬 상한. 0 이하 설정 시 데드락 방지를 위해 최소 1로 보정한다."""
    return max(1, _int_env("VERIFICATION_CONCURRENCY", 2))


def pipeline_llm_budget() -> int:
    """파이프라인 1회 실행당 최대 LLM 호출 허용 횟수 (서킷 브레이커)."""
    return _int_env("PIPELINE_LLM_BUDGET", 50)


def pipeline_timeout_sec() -> int:
    """모의고사 생성 API의 전체 실행 제한 시간."""
    return max(60, _int_env("MOCK_EXAM_PIPELINE_TIMEOUT_SEC", 900))


def examforge_answer_key_secret() -> str:
    """정답 키 위변조 방지용 HMAC secret."""
    secret = _required("EXAMFORGE_ANSWER_KEY_SECRET")
    if len(secret) < 32:
        raise RuntimeError("EXAMFORGE_ANSWER_KEY_SECRET는 32자 이상이어야 한다.")
    return secret


def exam_forge_port() -> int:
    """샌드박스 서버 포트."""
    return _int_env("MOCK_EXAM_PORT", 8900)


def codex_cli_model() -> str:
    """Codex CLI에 사용할 GPT 모델명."""
    return _optional("CODEX_CLI_MODEL") or "gpt-5.4"


def codex_cli_timeout_sec() -> int:
    """Codex CLI 단일 호출 타임아웃(초). 최소 60초."""
    return max(60, _int_env("CODEX_CLI_TIMEOUT_SEC", 300))


def log_level() -> str:
    """로그 출력 레벨."""
    return _optional("LOG_LEVEL") or "INFO"
