"""Modal 호출 재시도 헬퍼 및 응답 파싱 유틸.

재시도 로직 : 지수 백오프(1s → 2s → 4s), 최대 3회.
응답 파싱  : Modal 네이티브 dict → TTSResponse 변환 헬퍼.
세그먼트 병합: 분할 합성 결과 → 단일 WAV bytes.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable
from collections.abc import Mapping
from typing import TypeVar

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


def build_tts_response_from_modal_result(
    result: object,
    request: TTSRequest,
    model_name: str,
    fallback_latency_ms: float,
) -> TTSResponse:
    """Modal 네이티브 dict 응답을 TTSResponse 로 변환한다."""
    if not isinstance(result, Mapping):
        raise TypeError("Modal TTS 응답이 mapping 형식이 아니다.")
    audio_b64 = _mapping_str(result, "audio_b64")
    try:
        audio_bytes = base64.b64decode(audio_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Modal TTS audio_b64 가 올바른 base64 형식이 아니다.") from exc
    ref_text_used = _mapping_str_default(result, "ref_text_used", request.ref_text or "")
    return TTSResponse(
        audio_bytes=audio_bytes,
        sample_rate=_mapping_int(result, "sample_rate", 24000),
        content_type="audio/wav",
        duration_sec=_mapping_float(result, "duration_sec", 0.0),
        latency_ms=_mapping_float(result, "latency_ms", fallback_latency_ms),
        char_count=_mapping_int(result, "char_count", len(request.text)),
        model=_mapping_str_default(result, "model", model_name),
        auto_transcribed=False,
        resolved_ref_text=ref_text_used,
        ref_text_source="client" if ref_text_used else "empty_fallback",
        retry_count=0,
        quality_cer=None,
        quality_reason="not_reported",
        segment_count=1,
    )


def _mapping_str(data: Mapping[object, object], name: str) -> str:
    """필수 문자열 필드를 엄격하게 읽는다."""
    value = data[name]
    if not isinstance(value, str):
        raise TypeError(f"{name} 필드가 문자열이 아니다.")
    return value


def _mapping_str_default(data: Mapping[object, object], name: str, default: str) -> str:
    """선택 문자열 필드를 읽되 없으면 기본값을 쓴다."""
    value = data.get(name, default)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{name} 필드가 문자열이 아니다.")
    return value


def _mapping_int(data: Mapping[object, object], name: str, default: int) -> int:
    """Modal 숫자 필드를 정수로 정규화한다."""
    value = data.get(name, default)
    if isinstance(value, bool):
        raise TypeError(f"{name} 필드가 정수가 아니다.")
    return int(value)


def _mapping_float(data: Mapping[object, object], name: str, default: float) -> float:
    """Modal 숫자 필드를 실수로 정규화한다."""
    value = data.get(name, default)
    if isinstance(value, bool):
        raise TypeError(f"{name} 필드가 실수가 아니다.")
    return float(value)
