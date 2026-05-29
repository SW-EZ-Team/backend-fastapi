"""턴 커밋 및 플러시 처리 원자 모듈."""
from __future__ import annotations

import uuid

from app.modules.ASR_V1.connectors.asr_engine import ASREngine
from app.modules.ASR_V1.pipeline.audio_buffer import AudioBuffer
from app.modules.ASR_V1.pipeline.flush_policy import extract_flushable
from app.modules.ASR_V1.schemas.ws_messages import FinalTranscript, FlushSegment


async def execute_commit(
    buffer: AudioBuffer,
    engine: ASREngine,
    lang: str,
    flush_buffer: str,
) -> tuple[FinalTranscript | None, FlushSegment | None, str]:
    """버퍼 소비 → ASR 전사 → 플러시 정책 적용.
    Returns: (final_transcript or None, flush_segment or None, 갱신된 flush_buffer)
    Raises: ai_connectors 예외를 그대로 전파한다.
    """
    audio = buffer.consume_speech()
    if len(audio) == 0:
        return None, None, flush_buffer
    response = await engine.transcribe(audio, lang=lang)
    turn_id = str(uuid.uuid4())
    final = FinalTranscript(
        text=response.text,
        turn_id=turn_id,
        duration_sec=response.duration_sec,
        latency_ms=response.latency_ms,
    )
    new_buffer = flush_buffer + response.text
    segments, remaining = extract_flushable(new_buffer)
    flush = FlushSegment(segments=segments) if segments else None
    return final, flush, remaining
