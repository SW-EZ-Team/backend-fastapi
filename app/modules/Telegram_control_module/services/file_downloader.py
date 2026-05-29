"""Telegram getFile API로 파일 정보 조회 및 다운로드를 담당한다."""

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..config import DEFAULT_TIMEOUT_SECONDS
from ..config import TELEGRAM_API_BASE_URL
from .telegram_client import TelegramApiError


@dataclass(frozen=True)
class FileInfo:
    """Telegram getFile 응답에서 필요한 필드만 추린다."""

    file_id: str
    file_path: str
    file_size: int | None


def _get_file_info_sync(token: str, file_id: str) -> FileInfo:
    """Telegram getFile API를 동기 urllib로 호출한다."""
    url = f"{TELEGRAM_API_BASE_URL}/bot{token}/getFile?file_id={file_id}"
    request = urllib.request.Request(url=url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        raise TelegramApiError(_extract_description(raw_body) or "getFile 실패") from exc
    except urllib.error.URLError as exc:
        raise TelegramApiError("Telegram API 연결 실패") from exc

    data = _load_json(raw_body)
    if data.get("ok") is not True:
        raise TelegramApiError(str(data.get("description") or "getFile 응답 오류"))

    result = data.get("result")
    if not isinstance(result, dict):
        raise TelegramApiError("getFile result 형식 오류")

    file_path = result.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        raise TelegramApiError("getFile file_path 누락")

    raw_size = result.get("file_size")
    file_size = raw_size if isinstance(raw_size, int) and not isinstance(raw_size, bool) else None
    return FileInfo(file_id=file_id, file_path=file_path, file_size=file_size)


def _download_file_bytes_sync(token: str, file_path: str) -> bytes:
    """Telegram 파일 다운로드 URL에서 원본 바이트를 가져온다."""
    url = f"{TELEGRAM_API_BASE_URL}/file/bot{token}/{file_path}"
    request = urllib.request.Request(url=url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        raise TelegramApiError(_extract_description(raw_body) or "파일 다운로드 실패") from exc
    except urllib.error.URLError as exc:
        raise TelegramApiError("파일 다운로드 연결 실패") from exc


async def get_file_info(token: str, file_id: str) -> FileInfo:
    """이벤트 루프를 막지 않도록 getFile 호출을 스레드로 분리한다."""
    return await asyncio.to_thread(_get_file_info_sync, token, file_id)


async def download_file_bytes(token: str, file_path: str) -> bytes:
    """이벤트 루프를 막지 않도록 파일 다운로드를 스레드로 분리한다."""
    return await asyncio.to_thread(_download_file_bytes_sync, token, file_path)


def _load_json(raw_body: str) -> dict[str, object]:
    """응답 본문을 JSON 딕셔너리로 파싱한다."""
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise TelegramApiError("JSON 파싱 실패") from exc
    if not isinstance(data, dict):
        raise TelegramApiError("응답 형식 오류")
    return data


def _extract_description(raw_body: str) -> str | None:
    """오류 본문에서 Telegram description 필드를 추출한다."""
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    desc = data.get("description")
    return desc if isinstance(desc, str) else None
