"""RAG 하이브리드 검색 라우터 — JSON 요청을 받아 검색 결과를 반환한다.

connector.py 의 OCRv1Pipeline.search() 를 호출하고,
반환된 딕셔너리 목록을 OCRv1SearchResponse 로 변환해 응답한다.
"""
from __future__ import annotations

from fastapi import APIRouter

from ...connector import OCRv1Pipeline
from ...schemas.request import OCRv1SearchRequest
from ...schemas.response import OCRv1SearchResponse, SearchHit

router = APIRouter()


def _dicts_to_hits(raw_hits: list[dict]) -> list[SearchHit]:
    """검색 결과 딕셔너리 목록을 SearchHit 목록으로 변환한다."""
    hits: list[SearchHit] = []
    for h in raw_hits:
        hits.append(SearchHit(
            chunk_id=h.get("chunk_id", ""),
            text=h.get("text", ""),
            score=round(float(h.get("score", 0.0)), 4),
            section_title=h.get("section_title", ""),
            page_nums=h.get("page_nums", []),
        ))
    return hits


@router.post("/search", response_model=OCRv1SearchResponse, summary="RAG 하이브리드 검색")
async def search_chunks(body: OCRv1SearchRequest) -> OCRv1SearchResponse:
    """Qdrant 벡터 저장소에 대한 하이브리드 검색을 실행한다.

    - **query**: 검색 쿼리 문자열 (1~2000자)
    - **collection_name**: 검색 대상 컬렉션명
    - **top_k**: 반환할 최상위 결과 수 (1~50, 기본 5)
    """
    pipeline = OCRv1Pipeline()
    raw_hits = await pipeline.search(body.query, body.collection_name, body.top_k)
    hits = _dicts_to_hits(raw_hits)
    return OCRv1SearchResponse(
        query=body.query,
        hits=hits,
        total_found=len(hits),
    )
