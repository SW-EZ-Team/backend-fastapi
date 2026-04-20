"""텔레그램 모듈 환경 설정."""

import os

TELEGRAM_API_BASE_URL = "https://api.telegram.org"
TELEGRAM_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_WEBHOOK_SECRET_ENV = "TELEGRAM_WEBHOOK_SECRET"
DEFAULT_TIMEOUT_SECONDS = 10


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
