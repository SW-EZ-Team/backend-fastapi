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


def database_url() -> str:
    """PostgreSQL 접속 문자열을 반환한다."""
    value = _required_value("DATABASE_URL")
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


def database_schema() -> str:
    """PostgreSQL search_path에 사용할 schema 이름을 검증한다."""
    value = _optional_value("DATABASE_SCHEMA") or "chapter_studio"
    if not _SCHEMA_PATTERN.fullmatch(value):
        raise RuntimeError("DATABASE_SCHEMA 형식이 안전하지 않다.")
    return value


def anthropic_api_key() -> str | None:
    """Claude Planner 커넥터 API 키를 반환한다."""
    return _optional_value("ANTHROPIC_API_KEY")


def modal_token_id() -> str | None:
    """Modal 인증 토큰 ID를 반환한다."""
    return _optional_value("MODAL_TOKEN_ID")


def modal_token_secret() -> str | None:
    """Modal 인증 토큰 secret을 반환한다."""
    return _optional_value("MODAL_TOKEN_SECRET")


def active_text_model() -> str:
    """텍스트 생성 커넥터 이름을 반환한다."""
    return _optional_value("ACTIVE_TEXT_MODEL") or _optional_value("AI_MODEL") or "qwen27b_modal"


def active_planner_model() -> str:
    """Planner 커넥터 이름을 반환한다."""
    return _optional_value("ACTIVE_PLANNER_MODEL") or "opus46"


def active_tts_model() -> str:
    """TTS 커넥터 이름을 반환한다."""
    return _optional_value("ACTIVE_TTS_MODEL") or "tts_v1"


def tts_endpoint() -> str | None:
    """TTS V1 내부 엔드포인트를 반환한다."""
    return _optional_value("TTS_ENDPOINT") or _optional_value("TTS_V1_ENDPOINT")


def tts_ref_audio_path() -> Path | None:
    """WAV 응답형 TTS 엔드포인트에 보낼 기준 음성 경로를 반환한다."""
    value = _optional_value("TTS_REF_AUDIO_PATH")
    return Path(value).expanduser() if value is not None else None


def tts_ref_text() -> str | None:
    """기준 음성의 발화 텍스트를 반환한다."""
    return _optional_value("TTS_REF_TEXT")


def tts_output_dir() -> Path:
    """TTS WAV 응답을 저장할 로컬 출력 폴더를 반환한다."""
    value = _optional_value("TTS_OUTPUT_DIR") or "artifacts/tts_audio"
    return Path(value).expanduser()


def tts_timeout_sec() -> float:
    """장문 과외 대본 합성을 위한 TTS 호출 제한 시간을 반환한다."""
    raw_value = _optional_value("TTS_TIMEOUT_SEC") or "300"
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError("TTS_TIMEOUT_SEC는 숫자여야 한다.") from exc
    if value < 30 or value > 1200:
        raise RuntimeError("TTS_TIMEOUT_SEC는 30~1200초여야 한다.")
    return value


def qwen_app_name() -> str:
    """Modal에 배포된 Qwen vLLM 앱 이름을 반환한다."""
    return _optional_value("QWEN_APP_NAME") or "chapterstudio-qwen27b"


def codex_cli_model() -> str:
    """로컬 검증용 Codex CLI 모델 이름을 반환한다."""
    return _optional_value("CODEX_CLI_MODEL") or "gpt-5.4"


def codex_cli_reasoning_effort() -> str:
    """로컬 검증용 Codex CLI 추론 강도를 반환한다."""
    value = _optional_value("CODEX_CLI_REASONING_EFFORT") or "low"
    if value not in {"low", "medium", "high", "xhigh"}:
        raise RuntimeError("CODEX_CLI_REASONING_EFFORT 값이 올바르지 않다.")
    return value


def codex_cli_timeout_sec() -> int:
    """Codex CLI 단일 실행 제한 시간을 초 단위로 반환한다."""
    raw_value = _optional_value("CODEX_CLI_TIMEOUT_SEC") or "180"
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("CODEX_CLI_TIMEOUT_SEC는 정수여야 한다.") from exc
    if value < 30 or value > 600:
        raise RuntimeError("CODEX_CLI_TIMEOUT_SEC는 30~600초여야 한다.")
    return value


def log_level() -> str:
    """loguru 출력 레벨을 반환한다."""
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
