"""Telegram 명령 dispatcher 테스트."""
from __future__ import annotations

import pytest

from app.modules.Agent_orchestrator.job_store import job_store
from app.modules.Agent_orchestrator.schemas import AgentJobRequest
from app.modules.Telegram_control_module.schemas import TelegramMessageSummary
from app.modules.Telegram_control_module.services import command_dispatcher
from app.modules.Telegram_control_module.services.command_dispatcher import dispatch_telegram_command


class FakeTelegramClient:
    """전송 요청을 메모리에 보존하는 테스트 클라이언트."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_message(self, token: str, chat_id: str, message: str):
        self.sent.append((token, chat_id, message))


@pytest.mark.asyncio
async def test_dispatch_job_status_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """Telegram /job_status 명령이 job store 상태를 읽어 메시지로 보낸다."""
    record = job_store.create(
        AgentJobRequest(
            module="chapter_studio_v1",
            action="curriculum_preview",
            payload={},
        )
    )
    job_store.update(record.job_id, status="done", result={"ok": True})
    fake = FakeTelegramClient()
    monkeypatch.setattr(command_dispatcher, "get_default_bot_token", lambda: "token")

    handled = await dispatch_telegram_command(
        TelegramMessageSummary(
            telegram_chat_id=123,
            telegram_msg_id="1",
            content=f"/job_status {record.job_id}",
            message_type="text",
        ),
        fake,  # type: ignore[arg-type]
    )

    assert handled is True
    assert fake.sent == [
        ("token", "123", f"chapter_studio_v1/curriculum_preview 상태: done ({record.job_id})")
    ]


@pytest.mark.asyncio
async def test_dispatch_ignores_plain_text() -> None:
    """일반 텍스트는 Telegram ACK 외 추가 처리를 하지 않는다."""
    fake = FakeTelegramClient()
    handled = await dispatch_telegram_command(
        TelegramMessageSummary(
            telegram_chat_id=123,
            telegram_msg_id="1",
            content="안녕하세요",
            message_type="text",
        ),
        fake,  # type: ignore[arg-type]
    )
    assert handled is False
    assert fake.sent == []
