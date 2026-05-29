"""TTS V2 — 재시도 라우터 노드.

QC 실패 청크를 식별하고 재합성을 위해 audio_np 를 초기화한다.
재시도 횟수가 max_retries 를 초과한 청크는 failed_chunks 로 분류한다.

build_retry_profiles 는 synthesize_node 가 재시도 시 더 보수적인 파라미터로
합성하도록 유도하는 참조 유틸이다 (현재는 retry_count 기반으로 동작).
"""
from __future__ import annotations

import logging
import time

from app.modules.TTS_V2.schemas.state import AudiobookState, ChunkRecord

_LOG = logging.getLogger(__name__)


def _increment_and_reset(chunk: ChunkRecord) -> ChunkRecord:
    """재시도 카운트를 올리고 오디오를 초기화해 재합성 대상으로 전환한다."""
    return {
        **chunk,
        "retry_count": chunk.get("retry_count", 0) + 1,
        "audio_np": None,          # 재합성 강제 (audio_np=None 이면 synthesize_node 재처리)
        "qc_passed": False,
        "qc_reason": "pending",    # 다음 QC 사이클을 위해 초기화
    }


def _process_chunk(
    chunk: ChunkRecord,
    max_retries: int,
    failed_ids: list[str],
) -> ChunkRecord:
    """단일 청크에 재시도 정책을 적용하고 갱신된 ChunkRecord 를 반환한다."""
    if chunk.get("qc_passed", False):
        return chunk  # 이미 통과 — 변경 없음

    if chunk.get("retry_count", 0) >= max_retries:
        # 이미 상한 초과 (이전 사이클에서 처리됨)
        failed_ids.append(chunk.get("chunk_id", ""))
        return chunk

    next_count = chunk.get("retry_count", 0) + 1
    if next_count >= max_retries:
        # 마지막 재시도 — 오디오를 보존하고 실패 등록
        failed_ids.append(chunk.get("chunk_id", ""))
        return {**chunk, "retry_count": next_count}

    return _increment_and_reset(chunk)


def retry_router_node(state: AudiobookState) -> dict:
    """QC 실패 청크를 식별하고 재시도 플래그를 설정한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환
    if state.get("pipeline_status") == "error":
        return {}
    t_start = time.monotonic()
    max_retries: int = state.get("max_retries", 3)
    failed_ids: list[str] = list(state.get("failed_chunks", []))

    updated_chunks = [
        _process_chunk(chunk, max_retries, failed_ids)
        for chunk in state.get("chunks", [])
    ]

    elapsed_ms = (time.monotonic() - t_start) * 1000
    timings = {**state.get("timings", {}), "retry_router": elapsed_ms}
    return {
        "chunks": updated_chunks,
        "failed_chunks": failed_ids,
        "current_phase": "retrying",
        "timings": timings,
    }


def route_after_qc(state: AudiobookState) -> str:
    """조건부 엣지 라우팅 함수.

    Returns:
        "passed"   — 모든 청크가 QC 통과
        "retry"    — QC 실패 청크가 있고 재시도 가능
        "exhausted" — 재시도 상한 도달, 실패 청크 존재
    """
    max_retries: int = state.get("max_retries", 3)
    chunks = state.get("chunks", [])

    # 파이프라인 에러 상태이면 즉시 종료 경로
    if state.get("pipeline_status") == "error":
        _LOG.warning("QC 라우팅: pipeline_status=error — exhausted")
        return "exhausted"

    # chunks 가 비어 있으면 all()이 True 를 반환해 빈 WAV 파일이 HTTP 200으로
    # 정상 응답처럼 내보내지는 무성 데이터 오염을 방지한다.
    if not chunks:
        _LOG.warning("QC 라우팅: 청크 0건 — exhausted")
        return "exhausted"

    if all(c.get("qc_passed", False) for c in chunks):
        _LOG.info("QC 라우팅: 전체 %d건 통과 — passed", len(chunks))
        return "passed"

    # 재시도 가능한 실패 청크가 하나라도 있으면 retry
    for chunk in chunks:
        if not chunk.get("qc_passed", False) and chunk.get("retry_count", 0) < max_retries:
            _LOG.info("QC 라우팅: 재시도 가능 청크 발견 — retry (max=%d)", max_retries)
            return "retry"

    # 모두 상한 초과 — 강제 종료
    _LOG.warning("QC 라우팅: 전체 재시도 소진 — exhausted (max=%d)", max_retries)
    return "exhausted"
