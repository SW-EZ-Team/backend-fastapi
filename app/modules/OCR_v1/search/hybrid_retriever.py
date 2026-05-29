"""하이브리드 검색 오케스트레이터.

쿼리 텍스트를 임베딩 → Dense+Sparse 벡터 검색 → BGE-Reranker 재정렬 순으로
파이프라인을 실행하여 최종 순위가 매겨진 결과를 반환한다.

registry에서 컴포넌트를 가져오므로 구현체 변경 시 이 파일을 수정할 필요가 없다.
"""
from __future__ import annotations

import logging

from ..config import rerank_top_k

_LOG = logging.getLogger(__name__)


async def hybrid_search(
    query: str,
    collection_name: str,
    top_k: int = 5,
) -> list[dict]:
    """쿼리에 대해 하이브리드 검색을 수행하고 재정렬된 결과를 반환한다.

    실행 순서:
    1. 쿼리 텍스트 → Dense+Sparse 임베딩 (BGE-M3)
    2. Qdrant 하이브리드 검색 (RRF 기반)
    3. BGE-Reranker 재정렬
    4. 인용 형식으로 포맷
    """
    # registry에서 컴포넌트를 가져와 결합 — 구현체를 직접 임포트하지 않음
    from ..registry import get_embedder, get_reranker, get_store

    embedder = get_embedder()
    store = get_store()
    reranker = get_reranker()

    # 1단계: 쿼리 임베딩 — 단일 텍스트를 리스트로 감싸 embed() 호출
    query_embeddings = await embedder.embed([query])
    if not query_embeddings:
        _LOG.warning("쿼리 임베딩 실패: 빈 결과 반환")
        return []

    query_embedding = query_embeddings[0]

    # 2단계: 벡터 검색 — 리랭킹 입력용으로 top_k보다 넉넉히 가져옴
    search_top_k = rerank_top_k()
    raw_hits = await store.search(
        collection=collection_name,
        query_embedding=query_embedding,
        top_k=search_top_k,
    )

    if not raw_hits:
        return []

    # 3단계: 리랭킹 — payload의 텍스트를 사용
    documents = [hit.get("payload", {}).get("text", "") for hit in raw_hits]
    reranked = await reranker.rerank(query=query, documents=documents, top_k=top_k)

    # 4단계: 리랭킹 결과와 원본 payload를 병합
    results: list[dict] = []
    for item in reranked:
        original_idx = item["index"]
        if original_idx < len(raw_hits):
            hit = raw_hits[original_idx]
            results.append({
                "chunk_id": hit.get("id", ""),
                "score": item["score"],
                "text": item["text"],
                "payload": hit.get("payload", {}),
            })

    return results
