"""BGE-Reranker-v2-m3 Cross-Encoder 리랭커 구현체.

FlagReranker를 사용하여 (query, document) 쌍의 관련성 점수를 계산하고
상위 top_k 결과를 내림차순으로 반환한다.
싱글턴 모델 로딩으로 초기화 비용을 최소화한다.
"""
from __future__ import annotations

import asyncio
import logging

from ..config import reranker_model, rerank_top_k

_LOG = logging.getLogger(__name__)

# FlagEmbedding 지연 임포트
try:
    from FlagEmbedding import FlagReranker
    _FLAG_AVAILABLE = True
except ImportError:
    _FLAG_AVAILABLE = False
    _LOG.warning("FlagEmbedding 패키지가 설치되지 않았습니다. BGEReranker 비활성화.")

# 모듈 수준 상태 홀더 — global 문 없이 dict으로 싱글턴을 관리한다
_STATE: dict[str, "FlagReranker | None"] = {"reranker": None}
_reranker_lock = asyncio.Lock()


async def _ensure_reranker() -> "FlagReranker":
    """싱글턴 패턴으로 FlagReranker 모델을 로드한다.

    double-check + asyncio.Lock으로 동시 초기화 경쟁을 방지한다.
    """
    # dict 홀더를 통해 접근 — global 문 불필요
    if _STATE["reranker"] is not None:
        return _STATE["reranker"]

    async with _reranker_lock:
        if _STATE["reranker"] is not None:
            return _STATE["reranker"]

        model_name = reranker_model()
        _LOG.info("BGEReranker 모델 로딩 시작: %s", model_name)
        _STATE["reranker"] = await asyncio.to_thread(_load_reranker_sync, model_name)
        _LOG.info("BGEReranker 모델 로딩 완료: %s", model_name)

    return _STATE["reranker"]


def _load_reranker_sync(model_name: str) -> "FlagReranker":
    """동기 모델 로드 함수 — to_thread 내부에서 실행된다.

    Mac MPS 환경에서는 fp16 변환이 실패하므로 use_fp16=False로 로드한다.
    """
    import sys
    if not _FLAG_AVAILABLE:
        raise RuntimeError("FlagEmbedding 패키지가 설치되지 않아 BGEReranker를 로드할 수 없습니다.")
    # Apple Silicon(darwin) MPS에서는 fp16 .half() 호출이 충돌 — CPU fp32로 실행
    use_fp16 = sys.platform != "darwin"
    return FlagReranker(model_name, use_fp16=use_fp16)


class BGEReranker:
    """BGE-Reranker-v2-m3 기반 Cross-Encoder 리랭커.

    (query, document) 쌍의 관련성 점수를 계산하여
    가장 관련성 높은 top_k 문서를 반환한다.
    """

    name: str = "bge-reranker"

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[dict]:
        """쿼리와 문서 리스트를 받아 관련성 점수 기준으로 재정렬한 결과를 반환한다.

        반환 형식: [{"index": int, "text": str, "score": float}, ...]
        """
        if not documents:
            return []

        effective_top_k = top_k if top_k is not None else rerank_top_k()
        reranker = await _ensure_reranker()

        ranked = await asyncio.to_thread(
            _rerank_sync, reranker, query, documents, effective_top_k
        )
        return ranked


def _rerank_sync(
    reranker: "FlagReranker",
    query: str,
    documents: list[str],
    top_k: int,
) -> list[dict]:
    """동기 리랭킹 함수 — asyncio.to_thread 내부에서 실행된다.

    FlagReranker.compute_score()는 CPU/GPU 집약 연산이므로
    이벤트 루프 블로킹을 방지하기 위해 별도 스레드에서 실행한다.
    """
    pairs = [[query, doc] for doc in documents]
    scores: list[float] = reranker.compute_score(pairs, normalize=True)

    # (인덱스, 텍스트, 점수) 튜플로 묶어 점수 내림차순 정렬
    ranked = sorted(
        enumerate(zip(documents, scores)),
        key=lambda x: x[1][1],
        reverse=True,
    )[:top_k]

    return [
        {"index": idx, "text": text, "score": score}
        for idx, (text, score) in ranked
    ]
