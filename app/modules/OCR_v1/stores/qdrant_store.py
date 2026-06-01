"""Qdrant 벡터 저장소 구현체.

Dense(Cosine, 1024d) + Sparse Named Vector를 지원하는 컬렉션을 관리하며,
RRF(Reciprocal Rank Fusion) 기반 하이브리드 검색을 제공한다.
네트워크 오류에 대해서만 최대 3회 지수 백오프 재시도를 수행한다.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..config import qdrant_api_key, qdrant_url

_LOG = logging.getLogger(__name__)

# Qdrant 클라이언트 지연 임포트
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        PointStruct,
        SparseVector,
        SparseVectorParams,
        VectorParams,
    )
    _QDRANT_AVAILABLE = True
except ImportError:
    _QDRANT_AVAILABLE = False
    _LOG.warning("qdrant-client 패키지가 설치되지 않았습니다. QdrantStore 비활성화.")

_DENSE_DIM = 1024          # BGE-M3 Dense 벡터 차원
_MAX_RETRIES = 3           # 네트워크 오류 재시도 한계
_RETRY_BASE_SEC = 1.0      # 첫 재시도 대기 시간(초), 이후 2배씩 증가


class QdrantStore:
    """Qdrant 기반 VectorStore 구현체.

    ensure_collection → upsert → search 순서로 사용한다.
    ":memory:" URL이면 인메모리 클라이언트를 생성하여 테스트에 활용한다.
    """

    def __init__(self) -> None:
        # 클라이언트는 첫 호출 시 레이지 생성
        self._client: "QdrantClient | None" = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> "QdrantClient":
        """Qdrant 클라이언트 싱글턴을 반환한다."""
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is not None:
                return self._client
            url = qdrant_url()
            if not _QDRANT_AVAILABLE:
                raise RuntimeError("qdrant-client 미설치 — QdrantStore 사용 불가.")
            # ":memory:" URL이면 인메모리 클라이언트로 생성 (테스트용)
            if url == ":memory:":
                self._client = QdrantClient(":memory:")
            else:
                self._client = QdrantClient(url=url, api_key=qdrant_api_key())
            _LOG.info("Qdrant 클라이언트 생성: %s", url)
        return self._client

    async def ensure_collection(self, collection: str) -> None:
        """컬렉션이 없으면 Dense + Sparse Named Vector 스키마로 생성한다."""
        client = await self._get_client()
        exists = await asyncio.to_thread(
            lambda: client.collection_exists(collection)
        )
        if exists:
            return

        await asyncio.to_thread(
            client.create_collection,
            collection_name=collection,
            vectors_config={"dense": VectorParams(size=_DENSE_DIM, distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams()},
        )
        _LOG.info("Qdrant 컬렉션 생성: %s", collection)

    async def upsert(self, collection: str, points: list[dict]) -> int:
        """포인트 리스트를 배치 업서트하고 업서트 건수를 반환한다."""
        if not points:
            return 0

        client = await self._get_client()
        structured = [_build_point_struct(p) for p in points]

        await _retry(
            lambda: client.upsert(collection_name=collection, points=structured),
        )
        return len(structured)

    async def search(
        self,
        collection: str,
        query_embedding: dict,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """Dense + Sparse 하이브리드 검색을 수행하고 RRF 정렬 결과를 반환한다."""
        client = await self._get_client()

        dense_vec: list[float] = query_embedding.get("dense", [])
        sparse_data: dict = query_embedding.get("sparse", {"indices": [], "values": []})
        limit = top_k * 2  # RRF 입력용으로 넉넉히 가져옴

        sparse_vec = SparseVector(
            indices=sparse_data.get("indices", []),
            values=sparse_data.get("values", []),
        )

        # Dense/Sparse 검색 병렬 실행 (qdrant_client 1.x query_points() 사용)
        dense_hits_resp, sparse_hits_resp = await asyncio.gather(
            asyncio.to_thread(lambda: client.query_points(
                collection_name=collection,
                query=dense_vec,
                using="dense",
                limit=limit,
            )),
            asyncio.to_thread(lambda: client.query_points(
                collection_name=collection,
                query=sparse_vec,
                using="sparse",
                limit=limit,
            )),
        )
        dense_hits = dense_hits_resp.points
        sparse_hits = sparse_hits_resp.points

        return _rrf_merge(dense_hits, sparse_hits, top_k)


def _build_point_struct(point: dict) -> "PointStruct":
    """dict 포인트를 Qdrant PointStruct로 변환한다."""
    sparse_data = point.get("sparse", {"indices": [], "values": []})
    return PointStruct(
        id=point["id"],
        vector={
            "dense": point["dense"],
            "sparse": SparseVector(
                indices=sparse_data.get("indices", []),
                values=sparse_data.get("values", []),
            ),
        },
        payload=point.get("payload", {}),
    )


def _rrf_merge(
    dense_hits: list[Any],
    sparse_hits: list[Any],
    top_k: int,
    k: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion으로 Dense/Sparse 결과를 통합한다.

    k=60은 Qdrant 공식 RRF 기본값과 동일하다.
    """
    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}

    for rank, hit in enumerate(dense_hits, start=1):
        pid = str(hit.id)
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
        payloads[pid] = hit.payload or {}

    for rank, hit in enumerate(sparse_hits, start=1):
        pid = str(hit.id)
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
        payloads.setdefault(pid, hit.payload or {})

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_k]
    return [
        {"id": pid, "score": scores[pid], "payload": payloads[pid]}
        for pid in sorted_ids
    ]


async def _retry(fn: "Any", max_retries: int = _MAX_RETRIES) -> None:
    """네트워크 오류에 대해서만 지수 백오프 재시도를 수행한다.

    논리적 오류(잘못된 컬렉션명 등)는 재시도 없이 즉시 전파한다.
    """
    for attempt in range(max_retries):
        try:
            await asyncio.to_thread(fn)
            return
        except (ConnectionError, TimeoutError, OSError) as exc:
            if attempt >= max_retries - 1:
                raise
            wait = _RETRY_BASE_SEC * (2 ** attempt)
            _LOG.warning("Qdrant 재시도 %d/%d, %.1fs 대기: %s",
                         attempt + 1, max_retries, wait, exc)
            await asyncio.sleep(wait)
        except Exception as exc:
            _LOG.debug("비재시도 예외 전파: %s", type(exc).__name__)
            raise  # 논리적 오류는 재시도 없이 그대로 전파
