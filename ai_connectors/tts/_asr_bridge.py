"""TTS 커넥터의 ASR 보조 경로."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import numpy as np

from common.audio_io import encode_wav_bytes

from ..errors import InferenceError
from ..schemas import ASRRequest
from ..tts_schemas import TTSRequest
from ._quality_gate import TTSQualityResult, evaluate_roundtrip, is_ref_text_mismatch

if TYPE_CHECKING:
    from ..base import ASRConnector


async def resolve_ref_text(
    asr: ASRConnector | None,
    request: TTSRequest,
) -> tuple[str | None, bool, str]:
    """ref_text 의 실제 사용값과 소스를 확정한다."""
    if request.ref_text and request.ref_text.strip():
        client_text = request.ref_text.strip()
        if asr is None:
            return client_text, False, "client"
        asr_text = await transcribe_audio(asr, request.ref_audio_bytes, request.language)
        if asr_text and is_ref_text_mismatch(client_text, asr_text):
            return asr_text, True, "validated_auto_asr"
        return client_text, False, "client"
    if asr is None:
        return None, False, "empty_fallback"
    asr_text = await transcribe_audio(asr, request.ref_audio_bytes, request.language)
    if not asr_text:
        return None, False, "empty_fallback"
    return asr_text, True, "auto_asr"


async def evaluate_audio_quality(
    asr: ASRConnector | None,
    target_text: str,
    audio_np: np.ndarray,
    sample_rate: int,
    language: str,
) -> TTSQualityResult | None:
    """합성 결과 오디오를 ASR round-trip 으로 검증한다."""
    if asr is None:
        return None
    wav_bytes = await asyncio.to_thread(encode_wav_bytes, audio_np, sample_rate)
    transcript = await transcribe_audio(asr, wav_bytes, language)
    if not transcript:
        raise InferenceError("품질 게이트용 ASR 전사 결과가 비어 있습니다.")
    return evaluate_roundtrip(target_text, transcript)


async def transcribe_audio(
    asr: ASRConnector,
    audio_bytes: bytes,
    language: str,
) -> str:
    """품질 게이트와 ref_text 검증에 쓰는 공통 ASR 호출부."""
    response = await asr.generate(
        ASRRequest(audio_bytes=audio_bytes, language=map_asr_language(language))
    )
    return (response.text or "").strip()


def map_asr_language(language: str) -> str:
    """TTS 언어 힌트를 ASR 입력에서 쓸 코드로 맞춘다."""
    normalized = (language or "").strip().lower()
    if normalized in {"", "auto", "ko", "korean"}:
        return "ko"
    return normalized
