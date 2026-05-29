"""Agent job 실행기."""
from __future__ import annotations

import logging

from app.modules.Telegram_control_module.config import get_default_bot_token
from app.modules.Telegram_control_module.services.telegram_client import TelegramClient

from .adapters import dispatch_agent_job
from .callback import post_agent_callback
from .job_store import job_store
from .schemas import AgentJobRequest, utc_now

_LOG = logging.getLogger(__name__)


async def run_job(job_id: str, request: AgentJobRequest) -> None:
    """job을 실행하고 상태, callback, Telegram 알림을 갱신한다."""
    job_store.update(job_id, status="running", progress=0.1, current_stage="dispatch")
    try:
        result = await dispatch_agent_job(request)
    except Exception as exc:
        record = job_store.update(
            job_id,
            status="error",
            progress=1.0,
            current_stage="error",
            error_code=exc.__class__.__name__,
            error_message=str(exc),
        )
        await _callback(record)
        await _notify(job_id, request, success=False)
        return
    record = job_store.update(
        job_id,
        status="done",
        progress=1.0,
        current_stage="done",
        result=result,
    )
    await _callback(record)
    await _notify(job_id, request, success=True)


async def _callback(record) -> None:
    """Spring callback_url이 있으면 결과를 전송하고 상태를 보존한다."""
    if record.callback_url is None:
        return
    job_store.update(record.job_id, callback_status="pending")
    ok, attempts, error = await post_agent_callback(record)
    job_store.update(
        record.job_id,
        callback_status="sent" if ok else "failed",
        callback_attempts=attempts,
        callback_error=error or "",
        callback_last_at=utc_now(),
    )


async def _notify(job_id: str, request: AgentJobRequest, *, success: bool) -> None:
    """선택적으로 Telegram 알림을 보낸다. 토큰이 없으면 조용히 건너뛴다."""
    if request.notify_telegram_chat_id is None:
        return
    token = get_default_bot_token()
    if token is None:
        return
    status = "완료" if success else "실패"
    message = f"{request.module}/{request.action} job {status}: {job_id}"
    try:
        await TelegramClient().send_message(
            token=token,
            chat_id=request.notify_telegram_chat_id,
            message=message,
        )
    except Exception:
        _LOG.warning("텔레그램 알림 전송 실패", exc_info=True)
        return
