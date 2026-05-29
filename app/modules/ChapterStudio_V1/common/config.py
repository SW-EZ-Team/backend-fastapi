from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path

from dotenv import load_dotenv

_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@cache
def _load_env() -> None:
    """환경 파일은 공통 설정 계층에서 한 번만 로드한다."""
    load_dotenv()


def _optional_value(key: str) -> str | None:
    """빈 문자열은 설정되지 않은 값으로 취급한다."""
    _load_env()
    value = os.environ.get(key)
    if value is None or value == "":
        return None
    return value


def _required_value(key: str) -> str:
    """필수 환경값이 없으면 시작 단계에서 즉시 실패하게 한다."""
    value = _optional_value(key)
    if value is None:
        raise RuntimeError(f"{key}가 설정되지 않았다.")
    return value


def _float_value(key: str, default: str, min_value: float, max_value: float) -> float:
    """실수 환경값을 공통 범위 검증으로 읽는다."""
    raw_value = _optional_value(key) or default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{key}는 숫자여야 한다.") from exc
    if value < min_value or value > max_value:
        raise RuntimeError(f"{key}는 {min_value:g}~{max_value:g} 범위여야 한다.")
    return value


def _int_value(key: str, default: str, min_value: int, max_value: int) -> int:
    """정수 환경값을 공통 범위 검증으로 읽는다."""
    raw_value = _optional_value(key) or default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{key}는 정수여야 한다.") from exc
    if value < min_value or value > max_value:
        raise RuntimeError(f"{key}는 {min_value}~{max_value} 범위여야 한다.")
    return value


def database_url() -> str:
    value = _required_value("DATABASE_URL")
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


def database_schema() -> str:
    """PostgreSQL search_path에 사용할 schema 이름을 검증한다."""
    value = _optional_value("DATABASE_SCHEMA") or "chapter_studio"
    if not _SCHEMA_PATTERN.fullmatch(value):
        raise RuntimeError("DATABASE_SCHEMA 형식이 안전하지 않다.")
    return value


def anthropic_api_key() -> str | None:
    return _optional_value("ANTHROPIC_API_KEY")


def claude_sonnet_api_key() -> str | None:
    return _optional_value("CLAUDE_SONNET_API_KEY") or anthropic_api_key()


def claude_sonnet_model() -> str:
    return _optional_value("CLAUDE_SONNET_MODEL") or "claude-sonnet-4-5-20250929"


def claude_sonnet_timeout_sec() -> float:
    return _float_value("CLAUDE_SONNET_TIMEOUT_SEC", "300", 30, 1200)


def claude_sonnet_max_concurrency() -> int:
    return _int_value("CLAUDE_SONNET_MAX_CONCURRENCY", "4", 1, 8)


def gemini_api_key() -> str | None:
    return _optional_value("GEMINI_API_KEY")


def modal_token_id() -> str | None:
    return _optional_value("MODAL_TOKEN_ID")


def modal_token_secret() -> str | None:
    return _optional_value("MODAL_TOKEN_SECRET")


def active_text_model() -> str:
    return _optional_value("ACTIVE_TEXT_MODEL") or _optional_value("AI_MODEL") or "qwen27b_modal"


def active_planner_model() -> str:
    return _optional_value("ACTIVE_PLANNER_MODEL") or "opus46"


def active_tts_model() -> str:
    return _optional_value("ACTIVE_TTS_MODEL") or "tts_v1"


def tts_endpoint() -> str | None:
    return _optional_value("TTS_ENDPOINT") or _optional_value("TTS_V1_ENDPOINT")


def tts_ref_audio_path() -> Path | None:
    value = _optional_value("TTS_REF_AUDIO_PATH")
    return Path(value).expanduser() if value is not None else None


def tts_ref_text() -> str | None:
    return _optional_value("TTS_REF_TEXT")


def tts_output_dir() -> Path:
    value = _optional_value("TTS_OUTPUT_DIR") or "artifacts/tts_audio"
    return Path(value).expanduser()


def tts_timeout_sec() -> float:
    return _float_value("TTS_TIMEOUT_SEC", "300", 30, 1200)


def qwen_app_name() -> str:
    return _optional_value("QWEN_APP_NAME") or "chapterstudio-qwen27b"


def gemini_cli_model() -> str:
    return _optional_value("GEMINI_CLI_MODEL") or "gemini-2.5-pro"


def gemini_cli_timeout_sec() -> int:
    return _int_value("GEMINI_CLI_TIMEOUT_SEC", "240", 30, 600)


def gemini_cli_max_concurrency() -> int:
    return _int_value("GEMINI_CLI_MAX_CONCURRENCY", "1", 1, 4)


def text_fallback_connector() -> str:
    return _optional_value("TEXT_FALLBACK_CONNECTOR") or "claude_sonnet"


def text_fallback_after_failures() -> int:
    return _int_value("TEXT_FALLBACK_AFTER_FAILURES", "3", 1, 10)


def text_primary_attempt_timeout_sec() -> float:
    return _float_value("TEXT_PRIMARY_ATTEMPT_TIMEOUT_SEC", "180", 30, 1200)


def codex_cli_model() -> str:
    return _optional_value("CODEX_CLI_MODEL") or "gpt-5.4"


def codex_cli_reasoning_effort() -> str:
    """로컬 검증용 Codex CLI 추론 강도를 반환한다."""
    value = _optional_value("CODEX_CLI_REASONING_EFFORT") or "low"
    if value not in {"low", "medium", "high", "xhigh"}:
        raise RuntimeError("CODEX_CLI_REASONING_EFFORT 값이 올바르지 않다.")
    return value


def codex_cli_timeout_sec() -> int:
    return _int_value("CODEX_CLI_TIMEOUT_SEC", "180", 30, 600)


def log_level() -> str:
    return (_optional_value("LOG_LEVEL") or "INFO").upper()


@cache
def prepare_matplotlib_runtime() -> None:
    """matplotlib 캐시 경로를 쓰기 가능한 임시 경로로 고정한다."""
    mpl_dir = Path(_optional_value("MPLCONFIGDIR") or "/tmp/chapterstudio-matplotlib")
    xdg_dir = Path(_optional_value("XDG_CACHE_HOME") or "/tmp/chapterstudio-cache")
    mpl_dir.mkdir(parents=True, exist_ok=True)
    xdg_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(xdg_dir))
