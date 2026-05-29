"""TTS V2 — 낭독 계획 수립 노드.

AudiobookState 의 각 청크에 대해 normalized_text → planned_text 재작성을 수행한다.
ReadingPlanner (Kanana2 MLX) 를 통해 TTS 합성에 최적화된 텍스트로 변환한다.

ReadingPlanner 가 불가 상태이면 normalized_text 를 planned_text 로 그대로 복사해
파이프라인이 중단 없이 진행되도록 한다 (identity fallback).

SRP: 이 파일은 노드 레벨 오케스트레이터 (청크 순회 + 타이밍 기록).
"""
from __future__ import annotations

import time
import logging

from app.modules.TTS_V2.schemas.state import AudiobookState, ChunkRecord
from app.modules.TTS_V2.connectors.llm_planner import ReadingPlanner

_LOG = logging.getLogger(__name__)


def _rewrite_chunk(chunk: ChunkRecord, language: str) -> ChunkRecord:
    """단일 청크의 normalized_text 를 낭독용 planned_text 로 재작성한다.

    재작성 실패 또는 플래너 불가 시 normalized_text 를 planned_text 로 유지한다.
    """
    source = chunk.get("normalized_text", "")
    try:
        planned = ReadingPlanner.rewrite_for_reading(source, language=language)
    except Exception as exc:
        _LOG.warning("청크 %s 재작성 실패 — identity fallback: %s", chunk.get("chunk_id", "?"), exc)
        planned = source
    return {**chunk, "planned_text": planned}


def _is_planner_available() -> bool:
    """ReadingPlanner 가 사용 가능한지 확인한다.

    불가 플래그(_unavailable=True) 이면 조기 로드 시도 없이 False 반환.
    속성 접근 자체가 실패하면 불가로 간주한다.
    """
    try:
        if ReadingPlanner._unavailable:
            return False
        return True
    except Exception:
        _LOG.debug("ReadingPlanner 가용 확인 실패", exc_info=True)
        return False


def plan_reading_node(state: AudiobookState) -> dict:
    """각 청크의 normalized_text 를 낭독 최적화 텍스트로 재작성한다.

    ReadingPlanner 불가 시 normalized_text → planned_text identity 복사 후 계속 진행.
    """
    # 상위 노드에서 에러가 전파된 경우 즉시 반환
    if state.get("pipeline_status") == "error":
        return {}
    t_start = time.monotonic()
    language = state.get("language", "ko")

    # 청크가 없으면 계획 단계를 건너뛴다 — 빈 입력이 아래로 흘러내리지 않도록 조기 반환
    chunks = state.get("chunks", [])
    if not chunks:
        _LOG.warning("plan_reading_node: 청크 0건 — 계획 생략")
        elapsed_ms = (time.monotonic() - t_start) * 1000
        timings = {**state.get("timings", {}), "plan_reading": elapsed_ms}
        return {
            "chunks": [],
            "current_phase": "planning",
            "timings": timings,
        }

    if state.get("skip_planner", False) or not _is_planner_available():
        _LOG.warning("ReadingPlanner 건너뜀 — normalized_text 를 planned_text 로 복사")
        updated_chunks = [
            {**chunk, "planned_text": chunk.get("normalized_text", "")}
            for chunk in chunks
        ]
        elapsed_ms = (time.monotonic() - t_start) * 1000
        timings = {**state.get("timings", {}), "plan_reading": elapsed_ms}
        return {
            "chunks": updated_chunks,
            "current_phase": "planning",
            "timings": timings,
        }

    updated_chunks = []
    for chunk in chunks:
        updated_chunks.append(_rewrite_chunk(chunk, language))

    elapsed_ms = (time.monotonic() - t_start) * 1000
    timings = {**state.get("timings", {}), "plan_reading": elapsed_ms}
    return {
        "chunks": updated_chunks,
        "current_phase": "planning",
        "timings": timings,
    }
