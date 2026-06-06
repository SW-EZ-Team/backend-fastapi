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
    """신뢰 낮은 검증기에서는 검증 결과를 관측용으로만 사용한다.

    명시 플래그(EXAMFORGE_VERIFICATION_ADVISORY=true)일 때만 advisory 로 둔다.
    """
    return _bool_env("EXAMFORGE_VERIFICATION_ADVISORY", False)


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
    """문제 생성 병렬 상한. 0 이하 설정 시 데드락 방지를 위해 최소 1로 보정한다.

    기본값 3: codex 전역 세마포어(max_concurrent=3)와 일치시켜 노드 세마포어 ×
    codex 세마포어 조합으로 실 동시 codex 프로세스를 3 이하로 보장한다.
    env GENERATION_CONCURRENCY로 오버라이드 가능.
    """
    return max(1, _int_env("GENERATION_CONCURRENCY", 3))


def verification_concurrency() -> int:
    """정답 검증 병렬 상한. 0 이하 설정 시 데드락 방지를 위해 최소 1로 보정한다.

    기본값 3: codex 세마포어(3)가 상한을 보장하므로 높여도 폭주 없음.
    env VERIFICATION_CONCURRENCY로 오버라이드 가능.
    """
    return max(1, _int_env("VERIFICATION_CONCURRENCY", 3))


def pipeline_llm_budget() -> int:
    """파이프라인 1회 실행당 최대 LLM 호출 허용 횟수 (서킷 브레이커, 고정값 기본).

    문항 수를 모르는 호출부(테스트 더블 등)를 위한 폴백 기본값이다.
    실제 라우터는 pipeline_llm_budget_for(total_questions)로 문항 수 비례 예산을 쓴다.
    """
    return _int_env("PIPELINE_LLM_BUDGET", 80)


def pipeline_llm_budget_for(total_questions: int) -> int:
    """문항 수에 비례한 LLM 호출 예산을 계산한다.

    한 파이프라인 통과당 문항별 호출(생성·오답·해설·검증 ≈ 4단계)에 더해
    재시도 여유를 둔다. 정상 동작이 예산에 굶지 않도록 문항당 약 8회 + 고정 오버헤드.
    환경변수 PIPELINE_LLM_BUDGET가 명시되면 그 값을 하한으로 존중한다.

    예: 5문항 → 8*5+24 = 64, 10문항 → 8*10+24 = 104.
    """
    n = max(1, total_questions)
    scaled = n * _int_env("PIPELINE_LLM_BUDGET_PER_QUESTION", 8) + _int_env(
        "PIPELINE_LLM_BUDGET_OVERHEAD", 24
    )
    # 명시 고정값이 있으면 둘 중 큰 값을 쓴다(사용자 상향 의도 존중).
    explicit = _optional("PIPELINE_LLM_BUDGET")
    if explicit is not None:
        return max(scaled, _int_env("PIPELINE_LLM_BUDGET", 80))
    return scaled


def pipeline_llm_reserve_for(total_questions: int) -> int:
    """해설 생성(answer-gen) 전용으로 예약할 호출 수를 계산한다.

    출고되는 모든 문항이 완결 해설을 가지려면 최소 문항 수만큼의 해설 호출이
    필요하고, 파싱 재시도(문항당 최대 3회)를 감안해 여유를 둔다.
    환경변수 EXAMFORGE_ANSWER_RESERVE_PER_QUESTION로 조정 가능(기본 2).
    """
    n = max(1, total_questions)
    return n * _int_env("EXAMFORGE_ANSWER_RESERVE_PER_QUESTION", 2)


def pipeline_timeout_sec() -> int:
    """모의고사 생성 API의 전체 실행 제한 시간.

    기본 750초(12.5분): codex 초기 생성(~5분) + 1회 missing 재시도(~5분) + 여유(~2.5분).
    MOCK_EXAM_PIPELINE_TIMEOUT_SEC 환경변수로 조정 가능.
    """
    return max(60, _int_env("MOCK_EXAM_PIPELINE_TIMEOUT_SEC", 750))


def missing_retry_cap() -> int:
    """개수 부족(missing_count > 0) 전용 재시도 최대 횟수.

    이 횟수를 소진하면 추가 재시도 없이 확보된 유효 문항만으로 passed 출고한다.
    codex 속도(~5분/회)를 고려해 기본 1회로 제한한다.
    EXAMFORGE_MISSING_RETRY_CAP 환경변수로 조정 가능.
    """
    return max(0, _int_env("EXAMFORGE_MISSING_RETRY_CAP", 1))


def examforge_answer_key_secret() -> str:
    """정답 키 위변조 방지용 HMAC secret."""
    secret = _required("EXAMFORGE_ANSWER_KEY_SECRET")
    if len(secret) < 32:
        raise RuntimeError("EXAMFORGE_ANSWER_KEY_SECRET는 32자 이상이어야 한다.")
    return secret


def seal_enforce_mode() -> bool:
    """정답 키 seal 불일치 시 403을 강제할지 advisory(WARNING+계속)로 둘지 결정한다.

    기본값 false(advisory): 크로스서비스 canonical 재현이 반복 실패하는 동안
    403→502 차단을 해소하고 채점을 계속 진행하기 위해 advisory가 기본이다.
    내부 X-API-Key 인증 경로라 외부 변조 위험은 낮다.

    EXAMFORGE_SEAL_ENFORCE=true 로 명시하면 기존처럼 HMAC 불일치 시 403을 반환한다
    (canonical 정합이 확인된 뒤 재강제 시 사용).
    """
    return _bool_env("EXAMFORGE_SEAL_ENFORCE", default=False)


def exam_forge_port() -> int:
    """샌드박스 서버 포트."""
    return _int_env("MOCK_EXAM_PORT", 8900)


def log_level() -> str:
    """로그 출력 레벨."""
    return _optional("LOG_LEVEL") or "INFO"
