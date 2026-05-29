"""TTS V2 — 청크 병합 노드.

합성 완료된 청크들을 chunk_id 순서로 정렬 후 크로스페이드로 연결해
최종 WAV 바이트를 생성한다.
"""
from __future__ import annotations

import time

import numpy as np

from common.audio_io import encode_wav_bytes
from common.logging import get_logger
from app.modules.TTS_V2.pipeline.config import TTS_V2_CROSSFADE_MS
from app.modules.TTS_V2.processors.audio_postfx import crossfade_segments
from app.modules.TTS_V2.schemas.state import AudiobookState, ChunkRecord

_LOG = get_logger(__name__)


def _collect_audio_segments(chunks: list[ChunkRecord]) -> tuple[list[np.ndarray], int]:
    """QC 통과 + audio_np 존재 청크만 chunk_id 오름차순으로 수집한다.

    QC 실패 청크는 재시도 과정에서 audio_np 가 남아있을 수 있으므로
    qc_passed 필터로 최종 병합에서 제외해 품질 오염을 방지한다.
    """
    valid = sorted(
        (
            c for c in chunks
            if c.get("audio_np") is not None and c.get("qc_passed", False)
        ),
        key=lambda c: c.get("chunk_id", ""),
    )
    if not valid:
        return [], 24000
    sample_rate: int = valid[0].get("sample_rate", 24000)
    # sample_rate 일관성 검증 — 불일치 시 경고만 남기고 첫 번째 기준으로 진행
    for c in valid[1:]:
        c_sr = c.get("sample_rate", sample_rate)
        if c_sr != sample_rate:
            _LOG.warning(
                "청크 %s sample_rate 불일치: %d != %d",
                c.get("chunk_id", "?"), c_sr, sample_rate,
            )
    segments = [c.get("audio_np") for c in valid]
    return segments, sample_rate


def _compute_total_duration(merged: np.ndarray, sample_rate: int) -> float:
    """병합된 오디오의 총 길이(초)를 계산한다."""
    if sample_rate <= 0 or len(merged) == 0:
        return 0.0
    return float(len(merged)) / float(sample_rate)


def merge_node(state: AudiobookState) -> dict:
    """합성 완료 청크들을 순서대로 병합해 최종 WAV 를 생성한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환
    if state.get("pipeline_status") == "error":
        return {}
    t_start = time.monotonic()
    chunks = state.get("chunks", [])
    total_chunks = len(chunks)
    segments, sample_rate = _collect_audio_segments(chunks)

    elapsed_ms = (time.monotonic() - t_start) * 1000
    timings = {**state.get("timings", {}), "merge": elapsed_ms}

    # QC 통과 세그먼트가 없으면 에러 — 빈 WAV 를 성공으로 취급하지 않는다
    if not segments:
        _LOG.error("병합 실패: QC 통과 청크가 없어 유효 세그먼트 0개")
        return {
            "merged_audio_bytes": b"",
            "total_duration_sec": 0.0,
            "pipeline_status": "error",
            "error_message": "병합 실패: QC 통과 청크가 없음",
            "current_phase": "merging",
            "timings": timings,
        }

    try:
        merged = crossfade_segments(segments, sample_rate, crossfade_ms=TTS_V2_CROSSFADE_MS)
        merged_bytes = encode_wav_bytes(merged, sample_rate) if len(merged) > 0 else b""
    except Exception as exc:
        _LOG.exception("오디오 병합/인코딩 중 오류 발생")
        return {
            "merged_audio_bytes": b"",
            "total_duration_sec": 0.0,
            "pipeline_status": "error",
            "error_message": f"병합/인코딩 오류: {exc}",
            "current_phase": "merging",
            "timings": timings,
        }
    total_duration = _compute_total_duration(merged, sample_rate)

    elapsed_ms = (time.monotonic() - t_start) * 1000
    timings = {**state.get("timings", {}), "merge": elapsed_ms}

    # 일부 청크만 병합된 경우 부분 병합 경고 플래그를 설정한다
    merged_count = len(segments)
    is_partial = merged_count < total_chunks
    if is_partial:
        _LOG.warning(
            "부분 병합 감지: 전체 %d 청크 중 %d 개만 병합됨 (나머지 %d 개 QC 미통과)",
            total_chunks,
            merged_count,
            total_chunks - merged_count,
        )

    # 부분 병합이면 "partial", 전체 성공이면 "done" 으로 구분해 호출자가 식별할 수 있게 한다
    result = {
        "merged_audio_bytes": merged_bytes,
        "total_duration_sec": total_duration,
        "pipeline_status": "partial" if is_partial else "done",
        "current_phase": "merging",
        "timings": timings,
    }
    if is_partial:
        result["partial_merge"] = True
    return result
