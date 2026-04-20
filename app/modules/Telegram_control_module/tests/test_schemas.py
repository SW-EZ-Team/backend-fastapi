"""텔레그램 요청 스키마 단위 테스트."""

import pytest
from pydantic import ValidationError

from app.modules.Telegram_control_module import TelegramSendMessageRequest


def test_send_request_accepts_erd_telegram_chat_id() -> None:
    """ERD 정본 컬럼명인 telegram_chat_id 요청 필드를 받는다."""
    request = TelegramSendMessageRequest(token=" token ", telegram_chat_id=" 123 ", message=" 안녕 ")

    assert request.token == "token"
    assert request.chat_id == "123"
    assert request.telegram_chat_id == "123"
    assert request.message == "안녕"


def test_send_request_requires_message() -> None:
    """빈 메시지는 Telegram 전송 전에 스키마 단계에서 차단한다."""
    with pytest.raises(ValidationError):
        TelegramSendMessageRequest(token="token", telegram_chat_id="123", message=" ")
