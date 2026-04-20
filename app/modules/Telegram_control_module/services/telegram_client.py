"""Telegram Bot API 호출 클라이언트."""

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..config import DEFAULT_TIMEOUT_SECONDS
from ..config import TELEGRAM_API_BASE_URL
from ..schemas import TelegramSendMessageResult


class TelegramApiError(RuntimeError):
    """Telegram API 실패를 모듈 내부 예외로 정규화한다."""


@dataclass(frozen=True)
class TelegramClient:
    """표준 라이브러리만 사용해 배포 의존성을 늘리지 않는 Telegram 클라이언트."""

    base_url: str = TELEGRAM_API_BASE_URL
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    async def send_message(self, token: str, chat_id: str, message: str) -> TelegramSendMessageResult:
        """FastAPI 이벤트 루프를 막지 않도록 동기 HTTP 호출을 스레드로 분리한다."""
        return await asyncio.to_thread(self.send_message_sync, token, chat_id, message)

    def send_message_sync(self, token: str, chat_id: str, message: str) -> TelegramSendMessageResult:
        """Teletest의 sendMessage 검증 흐름을 Python 모듈로 옮긴다."""
        payload = {"chat_id": chat_id, "text": message}
        request = urllib.request.Request(
            url=f"{self.base_url}/bot{token}/sendMessage",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            raise TelegramApiError(_extract_error_description(raw_body) or "텔레그램 전송 실패") from exc
        except urllib.error.URLError as exc:
            raise TelegramApiError("텔레그램 API 연결 실패") from exc

        data = _load_json_object(raw_body)
        if data.get("ok") is not True:
            description = data.get("description")
            raise TelegramApiError(str(description or "텔레그램 전송 실패"))

        result = data.get("result")
        message_id = _extract_message_id(result)
        return TelegramSendMessageResult(ok=True, telegram_message_id=message_id)


def _load_json_object(raw_body: str) -> dict[str, object]:
    """Telegram 응답은 JSON 객체여야 하므로 다른 형태는 실패로 본다."""
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise TelegramApiError("텔레그램 응답 JSON 파싱 실패") from exc
    if not isinstance(data, dict):
        raise TelegramApiError("텔레그램 응답 형식 오류")
    return data


def _extract_error_description(raw_body: str) -> str | None:
    """HTTP 오류 본문에 포함된 Telegram description을 우선 노출한다."""
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    description = data.get("description")
    if isinstance(description, str):
        return description
    return None


def _extract_message_id(result: object) -> int | None:
    """발송 성공 시 Telegram message_id를 있으면 보존한다."""
    if not isinstance(result, dict):
        return None
    message_id = result.get("message_id")
    if isinstance(message_id, int) and not isinstance(message_id, bool):
        return message_id
    return None
