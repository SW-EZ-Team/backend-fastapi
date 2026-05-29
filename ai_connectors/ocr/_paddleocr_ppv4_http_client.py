"""PaddleOCR PP-OCRv4 Modal 엔드포인트 HTTP 클라이언트 원자 모듈.

커넥터 본체(`paddleocr_ppv4_connector.py`)에서 분리된 네트워크 호출 헬퍼.
SRP 준수 — "HTTP POST 보내고 정규화된 dict 반환"만 담당한다.
에러 정규화(vendor 오류 → 공유 예외)도 여기서 수행한다.
"""
from __future__ import annotations

import base64
import os
from typing import Any

import httpx

from ..errors import (
    AuthError,
    InferenceError,
    ModelLoadError,
    ModelNotFoundError,
    RateLimitError,
)
from ..errors import TimeoutError as ConnectorTimeoutError

_DEFAULT_TIMEOUT_SEC = 60.0
_DEFAULT_RETRIES = 1


def resolve_endpoint() -> str:
    """Modal 엔드포인트 URL 을 .env 에서 읽어 반환한다.

    `PADDLEOCR_PPV4_MODAL_URL` 이 비어있으면 ModelNotFoundError 를 던진다.
    """
    url = os.getenv("PADDLEOCR_PPV4_MODAL_URL", "").strip()
    if not url:
        raise ModelNotFoundError(
            "PADDLEOCR_PPV4_MODAL_URL 이 설정되지 않았습니다. "
            "`modal deploy modal/paddleocr_ppv4_modal_app.py` 실행 후 "
            "출력된 URL 을 .env 에 주입하세요.",
        )
    return url


def resolve_timeout() -> float:
    """타임아웃(초) — .env 의 PADDLEOCR_PPV4_TIMEOUT_SEC 우선."""
    raw = os.getenv("PADDLEOCR_PPV4_TIMEOUT_SEC", "").strip()
    try:
        return float(raw) if raw else _DEFAULT_TIMEOUT_SEC
    except ValueError:
        return _DEFAULT_TIMEOUT_SEC


def resolve_retries() -> int:
    """재시도 횟수 — .env 의 PADDLEOCR_PPV4_RETRIES 우선."""
    raw = os.getenv("PADDLEOCR_PPV4_RETRIES", "").strip()
    try:
        return max(0, int(raw)) if raw else _DEFAULT_RETRIES
    except ValueError:
        return _DEFAULT_RETRIES


def build_payload(image_bytes: bytes) -> dict[str, str]:
    """이미지 바이트를 Modal 엔드포인트 payload 로 변환한다."""
    return {"image_b64": base64.b64encode(image_bytes).decode("ascii")}


def normalize_http_error(exc: httpx.HTTPStatusError) -> Exception:
    """httpx HTTPStatusError 를 공유 예외 계층으로 정규화한다."""
    status = exc.response.status_code
    detail = _extract_detail(exc.response)
    if status in (401, 403):
        return AuthError(f"PaddleOCR Modal 인증 실패(status={status}): {detail}")
    if status == 404:
        return ModelNotFoundError(f"Modal 엔드포인트 미발견(status=404): {detail}")
    if status == 429:
        return RateLimitError(f"Modal 요청 한도 초과(status=429): {detail}")
    if status == 503:
        return ModelLoadError(f"Modal 모델 로드 대기(status=503): {detail}")
    return InferenceError(f"Modal 추론 실패(status={status}): {detail}")


def _extract_detail(response: httpx.Response) -> str:
    """httpx Response 본문에서 사람이 읽을 수 있는 오류 메시지를 추출한다."""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str):
                return detail
            return str(payload)
        return str(payload)
    except (ValueError, UnicodeDecodeError):
        try:
            return response.text[:200]
        except UnicodeDecodeError:
            return "<binary body>"


async def post_recognize(image_bytes: bytes) -> dict[str, Any]:
    """Modal 엔드포인트에 POST 하고 vendor JSON 응답을 dict 로 반환한다."""
    url = resolve_endpoint()
    timeout = resolve_timeout()
    retries = resolve_retries()
    payload = build_payload(image_bytes)

    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(retries + 1):
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise InferenceError(
                        f"PaddleOCR Modal 응답 형식이 dict 가 아님: {type(data).__name__}",
                    )
                return data
            except httpx.TimeoutException as exc:
                last_exc = ConnectorTimeoutError(
                    f"Modal 응답 타임아웃(attempt={attempt + 1}): {exc}",
                )
            except httpx.HTTPStatusError as exc:
                normalized = normalize_http_error(exc)
                if isinstance(normalized, (AuthError, ModelNotFoundError)):
                    raise normalized from exc
                last_exc = normalized
            except httpx.HTTPError as exc:
                last_exc = InferenceError(
                    f"Modal 네트워크 오류(attempt={attempt + 1}): {exc}",
                )
    assert last_exc is not None
    raise last_exc
