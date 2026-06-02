"""Modal HTTP 호출 재시도 헬퍼 및 응답 파싱 유틸.

재시도 로직 : 지수 백오프(1s → 2s → 4s), 최대 3회.
응답 파싱  : httpx.Response → TTSResponse 변환 헬퍼.
세그먼트 병합: 분할 합성 결과 → 단일 WAV bytes.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar
from urllib.parse import unquote

import httpx

from common.logging import get_logger
from ..errors import AuthError, ModelNotFoundError
from ..tts_schemas import TTSRequest, TTSResponse
from ._text_segmentation import merge_segment_responses as _merge_segment_response_bytes

_LOG = get_logger(__name__)

# 재시도 대기 시간(초) — 지수 백오프: 1, 2, 4
_BACKOFF_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)
# 재시도하지 않는 예외 — 클라이언트 오류이므로 반복해도 의미 없다
_NO_RETRY = (AuthError, ModelNotFoundError)

_T = TypeVar("_T")


async def call_with_retry(
    fn: Callable[[], Awaitable[_T]],
    max_attempts: int = 3,
) -> _T:
    """fn 을 최대 max_attempts 번 호출한다.

    _NO_RETRY 예외는 즉시 재올린다. 그 외 예외는 지수 백오프 후 재시도하며,
    마지막 시도에서도 실패하면 그대로 올린다.
    """
    # max_attempts >= 1 이 보장되므로 마지막 루프는 반드시 예외를 올리거나 반환한다
    last_exc: Exception = RuntimeError("call_with_retry: max_attempts 가 0 이하입니다")
    for attempt in range(max_attempts):
        try:
            return await fn()
        except _NO_RETRY:
            # 인증·404 오류는 재시도해도 변하지 않으므로 즉시 올린다
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                delay = _BACKOFF_DELAYS[attempt]
                _LOG.warning(
                    "Modal TTS 호출 실패 (시도 %d/%d). %.1f초 후 재시도. 오류: %s",
                    attempt + 1,
                    max_attempts,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
    raise last_exc


def merge_segment_responses(
    responses: list[TTSResponse],
    sample_rate: int,
    pause_ms: int | None = None,
) -> bytes:
    """기존 import 경로를 유지하면서 실제 병합 구현으로 위임한다."""
    return _merge_segment_response_bytes(responses, sample_rate, pause_ms=pause_ms)


def build_tts_response(
    response: httpx.Response,
    request: TTSRequest,
    model_name: str,
) -> TTSResponse:
    """httpx.Response 를 TTSResponse 로 변환한다."""
    content_type = response.headers.get("content-type", "audio/wav").split(";")[0]
    return TTSResponse(
        audio_bytes=response.content,
        sample_rate=_parse_int(response, "x-sample-rate", 24000),
        content_type=content_type,
        duration_sec=_parse_float(response, "x-duration-sec", 0.0),
        latency_ms=_parse_float(response, "x-latency-ms", 0.0),
        char_count=_parse_int(response, "x-char-count", len(request.text)),
        model=model_name,
        auto_transcribed=response.headers.get("x-auto-transcribed", "false") == "true",
        resolved_ref_text=unquote(
            response.headers.get("x-ref-text-used", request.ref_text or "")
        ),
        ref_text_source=response.headers.get("x-ref-text-source", "client"),
        retry_count=_parse_int(response, "x-retry-count", 0),
        quality_cer=_parse_optional_float(response, "x-quality-cer"),
        quality_reason=response.headers.get("x-quality-reason", "not_reported"),
        segment_count=_parse_int(response, "x-segment-count", 1),
    )


def extract_error_detail(response: httpx.Response) -> str:
    """에러 응답 본문에서 사람이 읽을 메시지를 뽑는다."""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict) and payload.get("detail"):
        return str(payload["detail"])
    return f"Modal TTS 호출 실패 (HTTP {response.status_code})"


def _parse_int(response: httpx.Response, name: str, default: int) -> int:
    """정수 헤더를 읽되 실패하면 기본값으로 되돌린다."""
    try:
        return int(response.headers.get(name, default))
    except (TypeError, ValueError):
        return default


def _parse_float(response: httpx.Response, name: str, default: float) -> float:
    """실수 헤더를 읽되 실패하면 기본값으로 되돌린다."""
    try:
        return float(response.headers.get(name, default))
    except (TypeError, ValueError):
        return default


def _parse_optional_float(response: httpx.Response, name: str) -> float | None:
    """없을 수도 있는 float 헤더를 안전하게 읽는다."""
    raw = response.headers.get(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None
