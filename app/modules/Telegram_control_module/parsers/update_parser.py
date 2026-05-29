"""Telegram Update 객체에서 필요한 필드를 추출한다."""

from collections.abc import Mapping

from ..schemas import TelegramMessageSummary

MESSAGE_KEYS = ("message", "edited_message", "channel_post", "edited_channel_post")


def extract_telegram_message_summary(update: Mapping[str, object]) -> TelegramMessageSummary | None:
    """수신·수정·콜백 메시지에서 ERD 기준 텔레그램 필드를 추출한다."""
    message = _extract_message(update)
    if message is None:
        return None

    chat = _as_mapping(message.get("chat"))
    if chat is None:
        return None

    chat_id = _to_int(chat.get("id"))
    if chat_id is None:
        return None

    file_id, file_name = _extract_file_id_and_name(message)
    return TelegramMessageSummary(
        telegram_chat_id=chat_id,
        telegram_msg_id=_to_telegram_msg_id(message.get("message_id")),
        telegram_username=_to_str(chat.get("username")),
        content=_extract_content(message),
        message_type=_extract_message_type(message),
        file_id=file_id,
        file_name=file_name,
    )


def _extract_message(update: Mapping[str, object]) -> Mapping[str, object] | None:
    """Telegram Update의 여러 메시지 위치를 하나의 탐색 순서로 통일한다."""
    for key in MESSAGE_KEYS:
        message = _as_mapping(update.get(key))
        if message is not None:
            return message

    callback_query = _as_mapping(update.get("callback_query"))
    if callback_query is None:
        return None
    return _as_mapping(callback_query.get("message"))


def _as_mapping(value: object) -> Mapping[str, object] | None:
    """중첩 JSON을 안전하게 내려가기 위한 타입 가드다."""
    if isinstance(value, Mapping):
        return value
    return None


def _to_int(value: object) -> int | None:
    """Telegram 외부 ID는 음수 채널 ID까지 보존하기 위해 int로 변환한다."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _to_str(value: object) -> str | None:
    """문자열 필드는 빈 값이면 없는 값으로 취급한다."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _to_telegram_msg_id(value: object) -> str | None:
    """ERD의 telegram_msg_id는 문자열 컬럼이므로 외부 ID를 문자열로 맞춘다."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return _to_str(value)


def _extract_content(message: Mapping[str, object]) -> str | None:
    """텍스트와 캡션 중 실제 저장 후보 본문을 고른다."""
    return _to_str(message.get("text")) or _to_str(message.get("caption"))


def _extract_message_type(message: Mapping[str, object]) -> str | None:
    """API 명세서의 Telegram 메시지 유형 이름을 우선순위대로 판별한다."""
    if _as_mapping(message.get("document")) is not None:
        return "document"
    if _as_mapping(message.get("voice")) is not None:
        return "voice"
    if isinstance(message.get("photo"), list):
        return "photo"
    if _to_str(message.get("text")) is not None:
        return "text"
    return None


def _extract_file_id_and_name(message: Mapping[str, object]) -> tuple[str | None, str | None]:
    """document 또는 photo에서 file_id와 파일명을 추출한다.

    document는 file_name 필드를 포함할 수 있지만 photo는 없으므로 None으로 둔다.
    photo는 배열의 마지막 요소가 가장 큰 해상도다.
    """
    doc = _as_mapping(message.get("document"))
    if doc is not None:
        file_id = _to_str(doc.get("file_id"))
        file_name = _to_str(doc.get("file_name"))
        return file_id, file_name

    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        largest = _as_mapping(photos[-1])
        if largest is not None:
            file_id = _to_str(largest.get("file_id"))
            return file_id, None

    return None, None
