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


def anthropic_api_key() -> str | None:
    """Anthropic API 키를 반환한다."""
    return _optional("ANTHROPIC_API_KEY")


def active_text_model() -> str:
    """텍스트 생성 커넥터 이름을 반환한다."""
    return _optional("ACTIVE_TEXT_MODEL") or "opus46"


def active_planner_model() -> str:
    """계획 수립 커넥터 이름을 반환한다."""
    return _optional("ACTIVE_PLANNER_MODEL") or "opus46"


def active_verifier_model() -> str:
    """검증용 커넥터 이름 (교차 검증에 사용)."""
    return _optional("ACTIVE_VERIFIER_MODEL") or "claude_sonnet"


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
