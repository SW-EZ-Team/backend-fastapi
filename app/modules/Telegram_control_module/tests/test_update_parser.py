"""텔레그램 Update 파서 단위 테스트."""

from app.modules.Telegram_control_module import extract_telegram_message_summary


def test_extract_telegram_message_summary_from_message() -> None:
    """일반 메시지에서 telegram_chat_id와 telegram_msg_id를 추출한다."""
    update = {
        "message": {
            "message_id": 17,
            "chat": {"id": 123456789, "username": "student_user", "first_name": "민준"},
            "text": "안녕하세요",
        }
    }

    summary = extract_telegram_message_summary(update)

    assert summary is not None
    assert summary.telegram_chat_id == 123456789
    assert summary.telegram_msg_id == "17"
    assert summary.telegram_username == "student_user"
    assert summary.content == "안녕하세요"
    assert summary.message_type == "text"


def test_extract_telegram_message_summary_from_callback_query() -> None:
    """콜백 쿼리 안의 메시지에서도 같은 방식으로 telegram_chat_id를 추출한다."""
    update = {
        "callback_query": {
            "message": {
                "message_id": 21,
                "chat": {"id": "-1001234567890"},
                "text": "버튼 클릭",
            }
        }
    }

    summary = extract_telegram_message_summary(update)

    assert summary is not None
    assert summary.telegram_chat_id == -1001234567890
    assert summary.telegram_msg_id == "21"
    assert summary.content == "버튼 클릭"
    assert summary.message_type == "text"


def test_extract_telegram_message_summary_returns_none_without_chat() -> None:
    """chat 정보가 없는 Update는 후속 저장 대상으로 보지 않는다."""
    update = {"message": {"message_id": 1, "text": "chat 없음"}}

    summary = extract_telegram_message_summary(update)

    assert summary is None
