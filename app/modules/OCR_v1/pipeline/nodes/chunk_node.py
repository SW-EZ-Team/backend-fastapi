"""LangGraph Stage 7 노드 — 섹션 기반 청킹.

후처리된 페이지 마크다운을 단일 문서로 합친 후
섹션 청커로 분할해 RAG 임베딩 단위인 ChunkRecord 목록을 생성한다.
"""
from __future__ import annotations

import logging
import time

from ...registry import get_chunker
from ...schemas.state import ChunkRecord, OCRPipelineState, PageExtraction

_LOG = logging.getLogger(__name__)

# 페이지 구분 마커 — 합본 마크다운에서 페이지 경계를 표시
_PAGE_MARKER_TPL = "\n\n<!-- page:{page_num} -->\n\n"


def _combine_pages(processed_pages: list[PageExtraction]) -> str:
    """처리된 페이지 마크다운을 페이지 마커와 함께 단일 문서로 합친다.

    청커가 page_nums 를 올바르게 추출할 수 있도록 마커를 삽입한다.
    키 누락 시 안전한 기본값을 사용해 KeyError 를 방지한다.
    """
    parts: list[str] = []
    for page in processed_pages:
        # .get() 으로 page_num/markdown 에 안전하게 접근
        marker = _PAGE_MARKER_TPL.format(page_num=page.get("page_num", 0))
        parts.append(marker + page.get("markdown", ""))
    return "".join(parts)


async def chunk_node(state: OCRPipelineState) -> dict:
    """합본 마크다운을 섹션 단위로 분할해 청크 목록을 생성한다.

    청커의 chunk() 는 비동기 함수이므로 직접 await 한다.
    오류 발생 시 pipeline_status 를 "error" 로 설정해 실패를 명시적으로 표현한다.
    """
    # 이전 단계에서 오류가 발생한 경우 즉시 반환 — 에러 전파로 불필요한 처리를 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    t0 = time.perf_counter()
    # .get() 으로 접근해 processed_pages 키 누락 시 빈 목록으로 안전하게 처리
    processed_pages: list = state.get("processed_pages", [])
    _LOG.info("Stage 7: 청킹 시작 — %d 페이지", len(processed_pages))

    # 입력 페이지 0건 — 업스트림에서 빈 결과가 전파된 경우
    if not processed_pages:
        _LOG.warning("Stage 7: 입력 페이지 0건 — 청킹 건너뜀")
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "chunks": [],
            "current_stage": "chunk",
            "pipeline_status": "partial",
            "error_message": "후처리된 페이지 0건 — 청킹 입력 없음",
            "timings": {**state.get("timings", {}), "chunk": elapsed},
        }

    try:
        chunker = get_chunker()
        combined_md = _combine_pages(processed_pages)
        # 청커에 PageExtraction 딕셔너리 목록을 그대로 전달 (TypedDict 는 dict 호환)
        raw_chunks: list[dict] = await chunker.chunk(combined_md, list(processed_pages))
    except Exception as exc:
        _LOG.exception("청킹 중 오류 발생")
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "pipeline_status": "error",
            "error_message": f"chunk_node 오류: {exc}",
            "current_stage": "chunk",
            "timings": {**state.get("timings", {}), "chunk": elapsed},
        }

    # dict → ChunkRecord 캐스팅 — 필드 불일치 시 개별 청크를 건너뛰고 경고
    chunks: list[ChunkRecord] = []
    for c in raw_chunks:
        try:
            chunks.append(ChunkRecord(**c))
        except (TypeError, KeyError) as exc:
            _LOG.warning("청크 캐스팅 실패 — 건너뜀: %s", exc)

    elapsed = round(time.perf_counter() - t0, 3)

    # 입력 페이지가 있는데 청크가 0건이면 부분 성공으로 처리해 호출자가 감지할 수 있게 한다
    if not chunks and processed_pages:
        _LOG.warning(
            "Stage 7: %d 페이지 처리 후 청크 0건 — 품질 저하 가능",
            len(processed_pages),
        )
        return {
            "chunks": [],
            "current_stage": "chunk",
            "pipeline_status": "partial",
            "error_message": f"{len(processed_pages)} 페이지 처리 후 청크 0건 — 텍스트 추출 품질 저하 가능",
            "timings": {**state.get("timings", {}), "chunk": elapsed},
        }

    _LOG.info("Stage 7 완료: %d 청크 생성, %.3fs 소요", len(chunks), elapsed)

    return {
        "chunks": chunks,
        "current_stage": "chunk",
        "timings": {**state.get("timings", {}), "chunk": elapsed},
    }
