"""텔레그램 제어 모듈 입출력 스키마."""

from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator


class TelegramSendMessageRequest(BaseModel):
    """테스트 콘솔과 내부 호출이 공통으로 쓰는 메시지 발송 요청."""

    token: str | None = Field(default=None, min_length=1)
    telegram_chat_id: str = Field(min_length=1)
    message: str = Field(min_length=1)

    @property
    def chat_id(self) -> str:
        """Telegram Bot API 호출용 chat_id 값을 ERD 필드에서 읽는다."""
        return self.telegram_chat_id

    @field_validator("token", "telegram_chat_id", "message", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        """브라우저 입력값의 앞뒤 공백은 서버에서도 한 번 더 제거한다."""
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class TelegramSendMessageResult(BaseModel):
    """Telegram sendMessage 호출 결과."""

    ok: bool
    telegram_message_id: int | None = None
    description: str | None = None


class TelegramAssignmentCaptionRequest(BaseModel):
    """과제 알림 캡션 생성과 Telegram 발송을 함께 요청한다."""

    telegram_chat_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    assignment: str = Field(min_length=1)
    weakness: str | None = Field(default=None, min_length=1)
    difficulty: str | None = Field(default=None, min_length=1)
    deadline: str | None = Field(default=None, min_length=1)

    @property
    def chat_id(self) -> str:
        """Telegram Bot API 호출용 chat_id 값을 ERD 필드에서 읽는다."""
        return self.telegram_chat_id

    @model_validator(mode="before")
    @classmethod
    def accept_chat_id_alias(cls, data: object) -> object:
        """프론트 시연 요청의 chat_id 별칭을 ERD 정본 필드로 맞춘다."""
        if not isinstance(data, dict):
            return data
        if "telegram_chat_id" in data or "chat_id" not in data:
            return data
        normalized = dict(data)
        normalized["telegram_chat_id"] = normalized["chat_id"]
        return normalized

    @field_validator(
        "telegram_chat_id",
        "name",
        "assignment",
        "weakness",
        "difficulty",
        "deadline",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        """브라우저 입력값의 앞뒤 공백은 서버에서도 한 번 더 제거한다."""
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class TelegramAssignmentCaptionResult(BaseModel):
    """과제 캡션 생성과 Telegram 발송 결과."""

    ok: bool
    text: str
    source: Literal["gemini", "kanana", "fallback"]
    telegram_message_id: int | None = None
    description: str | None = None


class TelegramMessageSummary(BaseModel):
    """웹훅 Update에서 `telegram_message` 저장 후보 필드를 요약한다."""

    telegram_chat_id: int
    telegram_msg_id: str | None = None
    telegram_username: str | None = None
    content: str | None = None
    message_type: str | None = None
    # 파일 제출 채점을 위한 Telegram 파일 식별자
    file_id: str | None = None
    file_name: str | None = None


class TelegramWebhookAck(BaseModel):
    """API 명세서의 `/telegram/webhook` 200 ACK 응답."""

    ok: bool
