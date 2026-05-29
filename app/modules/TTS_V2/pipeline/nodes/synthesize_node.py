"""TTS V2 — 음성 합성 노드.

AudiobookState 의 각 청크를 TTSEngineSession 으로 합성한다.
ref_audio 디코딩은 세션 init 에서 한 번만 수행하고, 청크마다 재사용한다.
이미 합성 완료(qc_passed=True, audio_np 존재)된 청크는 건너뛴다.
ICL 모드(ref_text 비어 있지 않음)에서는 합성 직후 레퍼런스 꼬리를 트리밍한다.
"""
from __future__ import annotations

import time

import numpy as np

from common.audio_io import duration_sec
from common.logging import get_logger
from app.modules.TTS_V2.connectors.tts_engine import TTSEngineSession
from app.modules.TTS_V2.connectors._icl_trimmer import trim_icl_prefix
from app.modules.TTS_V2.pipeline.config import TTS_V2_WHISPERX_MODEL
from app.modules.TTS_V2.schemas.state import AudiobookState, ChunkRecord

_LOG = get_logger(__name__)


def _should_skip(chunk: ChunkRecord) -> bool:
    """이미 합성 완료 및 QC 통과된 청크이면 True."""
    return chunk.get("audio_np") is not None and chunk.get("qc_passed") is True


def _apply_icl_trim(
    audio_np: np.ndarray,
    sr: int,
    expected_text: str,
    chunk_id: str,
) -> np.ndarray:
    """ICL 모드에서 레퍼런스 꼬리를 트리밍한다. 실패 시 원본을 반환한다."""
    trimmed, was_trimmed = trim_icl_prefix(
        audio_np, sr, expected_text, TTS_V2_WHISPERX_MODEL
    )
    if was_trimmed:
        _LOG.debug("청크 %s ICL 트리밍 적용 완료", chunk_id)
    return trimmed


def _synthesize_one(
    session: TTSEngineSession,
    chunk: ChunkRecord,
    ref_text: str,
    speed: float,
) -> ChunkRecord:
    """단일 청크를 합성하고 결과를 chunk 에 반영해 반환한다.

    ref_text 가 있으면 ICL 모드로 간주해 합성 후 레퍼런스 꼬리를 트리밍한다.
    합성 실패 시 audio_np 를 None 으로 두고 qc_passed=False 로 표기한다.
    """
    planned_text = chunk.get("planned_text", "")
    chunk_id = chunk.get("chunk_id", "unknown")
    try:
        audio_np, sr = session.synthesize_chunk(planned_text, speed=speed)
        # ICL 모드일 때만 레퍼런스 꼬리 트리밍 적용
        if ref_text:
            audio_np = _apply_icl_trim(audio_np, sr, planned_text, chunk_id)
        dur = duration_sec(audio_np, sr)
        return {
            **chunk,
            "audio_np": audio_np,
            "sample_rate": sr,
            "duration_sec": dur,
        }
    except Exception as exc:
        _LOG.warning(
            "청크 %s 합성 실패: %s — qc_passed=False 로 표기",
            chunk_id,
            exc,
        )
        return {
            **chunk,
            "audio_np": None,
            "qc_passed": False,
            "qc_reason": "synthesis_error",
        }


def synthesize_node(state: AudiobookState) -> dict:
    """각 청크를 순서대로 합성한다. TTSEngineSession 으로 ref_audio 를 캐싱한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환
    if state.get("pipeline_status") == "error":
        return {}
    t_start = time.monotonic()

    # 청크가 없으면 합성 단계를 건너뛴다 — 빈 상태가 세션 초기화 비용을 낭비하지 않도록 조기 반환
    chunks = state.get("chunks", [])
    if not chunks:
        _LOG.warning("synthesize_node: 청크 0건 — 합성 생략")
        elapsed_ms = (time.monotonic() - t_start) * 1000
        timings = {**state.get("timings", {}), "synthesize": elapsed_ms}
        return {
            "chunks": [],
            "current_phase": "synthesizing",
            "pipeline_status": "synthesizing",
            "timings": timings,
        }

    ref_text = state.get("ref_text", "")
    speed = float(state.get("speed", 1.0))
    updated_chunks: list = []
    try:
        # 세션 생성 및 합성 루프 전체를 try/except 로 감싸 예외 전파를 차단한다
        with TTSEngineSession(
            ref_audio_bytes=state.get("ref_audio_bytes", b""),
            ref_text=ref_text,
            ref_sr=state.get("ref_sample_rate", 24000),
            language=state.get("language", "ko"),
        ) as session:
            for chunk in chunks:
                if _should_skip(chunk):
                    _LOG.debug("청크 %s 이미 합성 완료 — 건너뜀", chunk.get("chunk_id", "?"))
                    updated_chunks.append(chunk)
                else:
                    updated_chunks.append(_synthesize_one(session, chunk, ref_text, speed))
    except Exception as exc:
        # TTSEngineSession 생성 자체가 실패한 경우 파이프라인 에러로 처리한다
        _LOG.error("TTSEngineSession 초기화 또는 합성 루프 실패: %s", exc)
        elapsed_ms = (time.monotonic() - t_start) * 1000
        timings = {**state.get("timings", {}), "synthesize": elapsed_ms}
        return {
            "chunks": updated_chunks or chunks,
            "current_phase": "synthesizing",
            "pipeline_status": "error",
            "error_message": f"합성 세션 오류: {exc}",
            "timings": timings,
        }

    elapsed_ms = (time.monotonic() - t_start) * 1000
    timings = {**state.get("timings", {}), "synthesize": elapsed_ms}
    return {
        "chunks": updated_chunks,
        "current_phase": "synthesizing",
        "pipeline_status": "synthesizing",
        "timings": timings,
    }
