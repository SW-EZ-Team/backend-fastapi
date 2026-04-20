"""Telegram_control_module FastAPI 라우터."""

from pathlib import Path

from fastapi import APIRouter
from fastapi import Header
from fastapi import HTTPException
from fastapi.responses import FileResponse

from ..config import get_default_bot_token
from ..config import get_webhook_secret
from ..parsers.update_parser import extract_telegram_message_summary
from ..schemas import TelegramSendMessageRequest
from ..schemas import TelegramSendMessageResult
from ..schemas import TelegramWebhookAck
from ..services.telegram_client import TelegramApiError
from ..services.telegram_client import TelegramClient

_CONSOLE_PATH = Path(__file__).resolve().parent.parent / "web_console" / "index.html"


def create_router(client: TelegramClient | None = None) -> APIRouter:
    """운영 코드와 테스트가 같은 라우터 팩토리를 쓰도록 한다."""
    telegram_client = client or TelegramClient()
    api_router = APIRouter(prefix="/telegram", tags=["telegram"])

    @api_router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "module": "Telegram_control_module"}

    @api_router.get("/console", include_in_schema=False)
    async def console() -> FileResponse:
        return FileResponse(_CONSOLE_PATH)

    @api_router.post("/sendMessage", response_model=TelegramSendMessageResult)
    async def send_message(request: TelegramSendMessageRequest) -> TelegramSendMessageResult:
        token = request.token or get_default_bot_token()
        if token is None:
            raise HTTPException(status_code=400, detail="봇 토큰이 필요합니다.")
        if not request.chat_id or not request.message:
            raise HTTPException(status_code=400, detail="telegram_chat_id와 메시지를 모두 입력해야 합니다.")

        try:
            return await telegram_client.send_message(
                token=token,
                chat_id=request.chat_id,
                message=request.message,
            )
        except TelegramApiError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api_router.post("/webhook", response_model=TelegramWebhookAck)
    async def webhook(
        update: dict[str, object],
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> TelegramWebhookAck:
        expected_secret = get_webhook_secret()
        if expected_secret is not None and x_telegram_bot_api_secret_token != expected_secret:
            raise HTTPException(status_code=400, detail="웹훅 secret token이 일치하지 않습니다.")

        extract_telegram_message_summary(update)
        return TelegramWebhookAck(ok=True)

    return api_router


router = create_router()
