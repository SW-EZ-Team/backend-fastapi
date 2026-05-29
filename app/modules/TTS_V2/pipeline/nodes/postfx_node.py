"""TTS V2 — 오디오 후처리 노드.

합성 완료된 각 청크에 postfx_pipeline(trim → LUFS normalize → peak limit)을 적용한다.
audio_np 가 None 인 청크(합성 실패 청크)는 건너뛴다.
"""
from __future__ import annotations

import time

from common.audio_io import duration_sec
from common.logging import get_logger
from app.modules.TTS_V2.pipeline.config import (
    TTS_V2_PEAK_DBFS,
    TTS_V2_TARGET_LUFS,
    TTS_V2_TRIM_THRESHOLD,
)
from app.modules.TTS_V2.processors.audio_postfx import postfx_pipeline
from app.modules.TTS_V2.schemas.state import AudiobookState, ChunkRecord

_LOG = get_logger(__name__)


def _apply_postfx(chunk: ChunkRecord) -> ChunkRecord:
    """단일 청크에 후처리를 적용한다. 실패 시 원본 chunk 를 그대로 반환한다."""
    audio_np = chunk.get("audio_np")
    sr = chunk.get("sample_rate", 24000)
    # audio_np 가 None 이면 합성 실패 청크 — 후처리 없이 그대로 반환
    if audio_np is None:
        return chunk
    try:
        processed = postfx_pipeline(
            audio_np,
            sr,
            target_lufs=TTS_V2_TARGET_LUFS,
            peak_dbfs=TTS_V2_PEAK_DBFS,
            trim_threshold=TTS_V2_TRIM_THRESHOLD,
        )
        dur = duration_sec(processed, sr)
        return {**chunk, "audio_np": processed, "duration_sec": dur}
    except Exception as exc:
        _LOG.warning("청크 %s 후처리 실패: %s — 원본 유지", chunk.get("chunk_id", "?"), exc)
        return chunk


def postfx_node(state: AudiobookState) -> dict:
    """각 청크의 오디오에 후처리를 적용한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환
    if state.get("pipeline_status") == "error":
        return {}
    t_start = time.monotonic()
    chunks = state.get("chunks", [])
    if state.get("skip_postfx", False):
        elapsed_ms = (time.monotonic() - t_start) * 1000
        timings = {**state.get("timings", {}), "postfx": elapsed_ms}
        return {
            "chunks": chunks,
            "current_phase": "postfx",
            "timings": timings,
        }
    updated_chunks = []
    degraded_count = 0
    for chunk in chunks:
        if chunk.get("audio_np") is None:
            # 합성 실패 청크는 후처리 없이 그대로 전달
            updated_chunks.append(chunk)
        else:
            processed = _apply_postfx(chunk)
            # _apply_postfx 가 원본을 반환했으면 후처리 실패로 간주
            if processed is chunk:
                degraded_count += 1
            updated_chunks.append(processed)
    if degraded_count > 0:
        _LOG.warning("후처리 실패 %d건 — 원본 오디오 유지", degraded_count)
    elapsed_ms = (time.monotonic() - t_start) * 1000
    timings = {**state.get("timings", {}), "postfx": elapsed_ms}
    return {
        "chunks": updated_chunks,
        "current_phase": "postfx",
        "timings": timings,
    }
