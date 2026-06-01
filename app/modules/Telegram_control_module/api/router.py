"""Telegram_control_module FastAPI 라우터."""

from __future__ import annotations

import asyncio
import hmac
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi import Header
from fastapi import HTTPException
from fastapi.responses import FileResponse

from common.db import get_connection
from ..config import get_default_bot_token
from ..config import get_webhook_secret
from ..parsers.update_parser import extract_telegram_message_summary
from ..schemas import TelegramAssignmentCaptionRequest
from ..schemas import TelegramAssignmentCaptionResult
from ..schemas import TelegramSendMessageRequest
from ..schemas import TelegramSendMessageResult
from ..schemas import TelegramWebhookAck
from ..services.command_dispatcher import dispatch_telegram_command
from ..services.telegram_client import TelegramApiError
from ..services.telegram_client import TelegramClient

if TYPE_CHECKING:
    from app.modules.AI_CPU_Kanana_Nano_Q4.caption import CaptionResult

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

    @api_router.post(
        "/send-assignment-caption",
        response_model=TelegramAssignmentCaptionResult,
    )
    async def send_assignment_caption(
        request: TelegramAssignmentCaptionRequest,
    ) -> TelegramAssignmentCaptionResult:
        token = get_default_bot_token()
        if token is None:
            raise HTTPException(status_code=400, detail="봇 토큰이 필요합니다.")

        caption = await asyncio.to_thread(_generate_assignment_caption, request)
        try:
            sent = await telegram_client.send_message(
                token=token,
                chat_id=request.chat_id,
                message=caption.text,
            )
        except TelegramApiError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return TelegramAssignmentCaptionResult(
            ok=sent.ok,
            text=caption.text,
            source=caption.source,
            telegram_message_id=sent.telegram_message_id,
            description=sent.description,
        )

    @api_router.post("/webhook", response_model=TelegramWebhookAck)
    async def webhook(
        update: dict[str, object],
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> TelegramWebhookAck:
        expected_secret = get_webhook_secret()
        if expected_secret is not None and not hmac.compare_digest(
            (x_telegram_bot_api_secret_token or "").encode(),
            expected_secret.encode(),
        ):
            raise HTTPException(status_code=400, detail="웹훅 secret token이 일치하지 않습니다.")

        summary = extract_telegram_message_summary(update)
        # 공유 풀에서 DB 커넥션을 획득한다 — 풀 미초기화 시 커넥션 없이 진행
        try:
            async with get_connection() as db_conn:
                await dispatch_telegram_command(summary, telegram_client, db_pool=db_conn)
        except HTTPException:
            # DB 미설정 시 커넥션 없이 진행
            await dispatch_telegram_command(summary, telegram_client, db_pool=None)
        return TelegramWebhookAck(ok=True)

    return api_router


def _generate_assignment_caption(
    request: TelegramAssignmentCaptionRequest,
) -> "CaptionResult":
    """라우터 수집 시점에는 무거운 캡션 패키지 import를 피한다."""
    generate_caption = _load_generate_caption()

    return generate_caption(
        student_name=request.name,
        assignment_name=request.assignment,
        weakness=request.weakness,
        difficulty=request.difficulty,
        deadline=request.deadline,
    )


def _load_generate_caption() -> "Callable[..., CaptionResult]":
    """테스트 스텁이 패키지 import를 가린 경우 실제 모듈을 다시 찾는다."""
    try:
        from app.modules.AI_CPU_Kanana_Nano_Q4.caption import generate_caption

        return generate_caption
    except (ImportError, AttributeError):
        _clear_shadowed_caption_packages()
        from app.modules.AI_CPU_Kanana_Nano_Q4.caption import generate_caption

        return generate_caption


def _clear_shadowed_caption_packages() -> None:
    """패키지 경로가 없는 테스트용 스텁만 제거한다."""
    for name in (
        "app",
        "app.modules",
        "app.modules.AI_CPU_Kanana_Nano_Q4",
    ):
        module = sys.modules.get(name)
        if module is not None and not hasattr(module, "__path__"):
            sys.modules.pop(name, None)


router = create_router()
