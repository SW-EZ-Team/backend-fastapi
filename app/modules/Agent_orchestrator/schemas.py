"""Agent orchestrator 공통 job 스키마."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

AgentModule = Literal["chapter_studio_v1", "tts_v2", "exam_forge_v1", "ocr_v1", "chat_v1"]
AgentJobStatus = Literal["queued", "running", "done", "error", "cancelled"]
AgentCallbackStatus = Literal["not_requested", "pending", "sent", "failed"]


def utc_now() -> datetime:
    """timezone-aware UTC 시각을 반환한다."""
    return datetime.now(timezone.utc)


def new_job_id() -> str:
    """외부 추적용 job id를 생성한다."""
    return f"job_{uuid4().hex}"


class AgentJobRequest(BaseModel):
    """Spring/Telegram/프론트가 공통으로 사용할 비동기 job 생성 요청."""

    request_id: str | None = Field(default=None, min_length=1, max_length=120)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=120)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=160)
    module: AgentModule
    action: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    callback_url: str | None = Field(default=None, min_length=1, max_length=2000)
    notify_telegram_chat_id: str | None = Field(default=None, min_length=1)
    run_inline: bool = Field(default=False, description="테스트/짧은 preview용 즉시 실행 플래그")

    @field_validator(
        "request_id",
        "correlation_id",
        "idempotency_key",
        "action",
        "callback_url",
        "notify_telegram_chat_id",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        """공백 문자열을 정리한다."""
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class AgentJobRecord(BaseModel):
    """인메모리 job 상태 레코드."""

    job_id: str = Field(default_factory=new_job_id)
    request_id: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    module: AgentModule
    action: str
    status: AgentJobStatus = "queued"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    current_stage: str = Field(default="queued", min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | list[Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    callback_url: str | None = None
    callback_status: AgentCallbackStatus = "not_requested"
    callback_attempts: int = Field(default=0, ge=0)
    callback_error: str | None = None
    callback_last_at: datetime | None = None
    notify_telegram_chat_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
