"""TTS V2 — 텍스트 청킹 노드.

clean_text_node 에서 정규화된 sections 를 ChunkRecord 리스트로 분할한다.
chunk_sections 는 skip=True 섹션을 자동으로 제외한다.
"""
from __future__ import annotations

import logging
import time

from app.modules.TTS_V2.pipeline.config import TTS_V2_CHUNK_MAX_CHARS, TTS_V2_CHUNK_MIN_CHARS
from app.modules.TTS_V2.processors.semantic_chunker import chunk_sections
from app.modules.TTS_V2.schemas.state import AudiobookState, ChunkRecord

_LOG = logging.getLogger(__name__)


def _to_chunk_record(raw: dict) -> ChunkRecord:
    """semantic_chunker 출력 dict 를 완전한 ChunkRecord 로 변환한다.

    original_text / normalized_text / planned_text 는 모두 raw["original_text"] 로
    초기화되며, 이후 노드에서 각각 갱신된다.
    """
    text = raw.get("original_text", "")
    return {
        "chunk_id": raw.get("chunk_id", ""),
        "chapter_idx": raw.get("chapter_idx", 0),
        "section_title": raw.get("section_title", ""),
        "original_text": text,
        "normalized_text": text,   # clean_text_node 에서 이미 정규화됨
        "planned_text": text,      # plan_reading_node 에서 재작성됨
        "audio_np": None,
        "sample_rate": 24000,
        "duration_sec": 0.0,
        "cer": None,
        "wer": None,
        "qc_passed": False,
        "retry_count": 0,
        "qc_reason": "pending",
    }


def chunk_text_node(state: AudiobookState) -> dict:
    """sections 를 ChunkRecord 리스트로 분할한다."""
    # 파이프라인 에러 상태이면 즉시 반환해 하위 노드 실행을 막는다
    if state.get("pipeline_status") == "error":
        return {}
    t_start = time.monotonic()
    try:
        raw_chunks = chunk_sections(
            state.get("sections", []),
            min_chars=TTS_V2_CHUNK_MIN_CHARS,
            max_chars=TTS_V2_CHUNK_MAX_CHARS,
        )
        chunks: list[ChunkRecord] = [_to_chunk_record(r) for r in raw_chunks]
    except Exception as exc:
        _LOG.exception("chunk_sections 처리 중 오류 발생")
        return {
            "chunks": [],
            "pipeline_status": "error",
            "error_message": f"텍스트 청킹 실패: {exc}",
            "timings": {**state.get("timings", {}), "chunk_text": (time.monotonic() - t_start) * 1000},
        }
    # 입력 섹션이 있는데 청크가 0건이면 경고 로그를 남긴다
    if not chunks and state.get("sections"):
        _LOG.warning("chunk_text_node: 섹션 %d건에서 청크 0건 — 후속 노드에 빈 입력 전달", len(state.get("sections", [])))
    elapsed_ms = (time.monotonic() - t_start) * 1000
    timings = {**state.get("timings", {}), "chunk_text": elapsed_ms}
    return {
        "chunks": chunks,
        "current_phase": "chunking",
        "timings": timings,
    }
