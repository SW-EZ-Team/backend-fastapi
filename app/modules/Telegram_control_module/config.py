"""텔레그램 모듈 환경 설정."""

import os

TELEGRAM_API_BASE_URL = "https://api.telegram.org"
TELEGRAM_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_WEBHOOK_SECRET_ENV = "TELEGRAM_WEBHOOK_SECRET"
DEFAULT_TIMEOUT_SECONDS = 10

# Claude VLM 채점 관련 환경변수 — ChapterStudio와 동일한 키 공유
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
GRADING_MODEL_ENV = "GRADING_SONNET_MODEL"
GRADING_MODEL_DEFAULT = "claude-sonnet-4-20250514"
DATABASE_URL_ENV = "DATABASE_URL"
# VLM 채점은 일반 텍스트 생성보다 시간이 더 필요하다
GRADING_TIMEOUT_SECONDS = 60


def get_default_bot_token() -> str | None:
    """봇 토큰은 코드가 아니라 환경변수에서만 읽는다."""
    token = os.getenv(TELEGRAM_BOT_TOKEN_ENV)
    if token is None:
        return None
    stripped = token.strip()
    return stripped or None


def get_webhook_secret() -> str | None:
    """웹훅 secret token은 설정된 경우에만 검증한다."""
    secret = os.getenv(TELEGRAM_WEBHOOK_SECRET_ENV)
    if secret is None:
        return None
    stripped = secret.strip()
    return stripped or None


def get_grading_api_key() -> str | None:
    """Claude VLM 채점용 Anthropic API 키를 환경변수에서 읽는다."""
    key = os.getenv(ANTHROPIC_API_KEY_ENV)
    if key is None:
        return None
    stripped = key.strip()
    return stripped or None


def get_grading_model() -> str:
    """채점에 사용할 Claude 모델명을 반환한다. 미설정 시 기본값을 쓴다."""
    model = os.getenv(GRADING_MODEL_ENV, "").strip()
    return model or GRADING_MODEL_DEFAULT


def get_database_url() -> str | None:
    """asyncpg 연결용 DATABASE_URL을 환경변수에서 읽는다."""
    url = os.getenv(DATABASE_URL_ENV)
    if url is None:
        return None
    stripped = url.strip()
    return stripped or None
