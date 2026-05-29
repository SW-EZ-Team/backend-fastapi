"""Telegram 텍스트 명령 및 파일 제출을 내부 서비스로 연결한다."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.modules.Agent_orchestrator.job_store import JobNotFoundError, job_store

from ..config import get_default_bot_token
from ..schemas import TelegramMessageSummary
from .telegram_client import TelegramClient

if TYPE_CHECKING:
    from app.core.weakness_service import WeaknessConnection

# 파일 제출로 인식하는 메시지 유형 집합
_FILE_MESSAGE_TYPES = {"document", "photo"}


async def dispatch_telegram_command(
    summary: TelegramMessageSummary | None,
    client: TelegramClient,
    db_pool: "WeaknessConnection | None" = None,
) -> bool:
    """지원하는 Telegram 명령 또는 파일 제출이면 처리하고 True를 반환한다."""
    if summary is None:
        return False

    # 파일 제출 우선 처리 — content가 없어도 file_id가 있으면 채점 흐름으로 간다
    if summary.message_type in _FILE_MESSAGE_TYPES and summary.file_id:
        if db_pool is not None:
            await _handle_file_grading(summary, client, db_pool)
        return True

    if summary.content is None:
        return False
    parts = summary.content.strip().split()
    if not parts:
        return False
    command = parts[0].lower()
    if command not in {"/job_status", "/status"}:
        return False
    message = _job_status_message(parts[1] if len(parts) > 1 else "")
    await _send_if_configured(client, summary.telegram_chat_id, message)
    return True


async def _handle_file_grading(
    summary: TelegramMessageSummary,
    client: TelegramClient,
    db_conn: "WeaknessConnection",
) -> None:
    """파일 제출 채점 오케스트레이터를 호출한다."""
    # 순환 임포트 방지를 위해 함수 내부에서 임포트한다
    from .grading_orchestrator import handle_file_submission

    file_name = summary.file_name or _default_file_name(summary.message_type)
    await handle_file_submission(
        summary=summary,
        file_id=summary.file_id,  # type: ignore[arg-type]  # 호출 전 None 확인 완료
        file_name=file_name,
        client=client,
        db_conn=db_conn,
    )


def _default_file_name(message_type: str | None) -> str:
    """파일명이 없을 때 메시지 유형 기반 기본 이름을 반환한다."""
    if message_type == "photo":
        return "submission.jpg"
    return "submission.pdf"


def _job_status_message(job_id: str) -> str:
    """job_id에 대한 사용자용 상태 문장을 만든다."""
    if not job_id:
        return "사용법: /job_status job_<id>"
    try:
        record = job_store.get(job_id)
    except JobNotFoundError:
        return f"job을 찾을 수 없습니다: {job_id}"
    if record.status == "error":
        return f"{record.module}/{record.action} 실패: {record.error_message or record.error_code or job_id}"
    return f"{record.module}/{record.action} 상태: {record.status} ({record.job_id})"


async def _send_if_configured(
    client: TelegramClient,
    telegram_chat_id: int,
    message: str,
) -> None:
    """봇 토큰이 설정된 경우에만 메시지를 전송한다."""
    token = get_default_bot_token()
    if token is None:
        return
    await client.send_message(
        token=token,
        chat_id=str(telegram_chat_id),
        message=message,
    )
