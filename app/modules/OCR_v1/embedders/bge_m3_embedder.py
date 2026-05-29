"""BGE-M3 임베더 구현체.

FlagEmbedding의 BGEM3FlagModel을 사용하여 Dense(1024차원) + Sparse 벡터를
단일 forward pass로 생성한다. 싱글턴 모델 로딩과 asyncio.Lock으로
동시 초기화 경쟁을 방지한다.
"""
from __future__ import annotations

import asyncio
import logging

from ..config import embedding_batch_size, embedding_model

_LOG = logging.getLogger(__name__)

# FlagEmbedding 지연 임포트 — 미설치 환경 허용
try:
    from FlagEmbedding import BGEM3FlagModel
    _FLAG_AVAILABLE = True
except ImportError:
    _FLAG_AVAILABLE = False
    _LOG.warning("FlagEmbedding 패키지가 설치되지 않았습니다. BGEM3Embedder 비활성화.")

# 모듈 수준 상태 홀더 — global 문 없이 dict으로 싱글턴을 관리한다
_STATE: dict[str, "BGEM3FlagModel | None"] = {"model": None}
_model_lock = asyncio.Lock()


async def _ensure_model() -> "BGEM3FlagModel":
    """싱글턴 패턴으로 BGE-M3 모델을 로드한다.

    asyncio.Lock + double-check 패턴으로 동시 초기화를 방지한다.
    모델 로드는 CPU/GPU를 사용하므로 to_thread로 감싼다.
    """
    # dict 홀더를 통해 접근 — global 문 불필요
    if _STATE["model"] is not None:
        return _STATE["model"]

    async with _model_lock:
        # 락 획득 후 다시 확인 — 다른 코루틴이 이미 로드했을 수 있음
        if _STATE["model"] is not None:
            return _STATE["model"]

        model_name = embedding_model()
        _LOG.info("BGE-M3 모델 로딩 시작: %s", model_name)
        _STATE["model"] = await asyncio.to_thread(_load_model_sync, model_name)
        _LOG.info("BGE-M3 모델 로딩 완료: %s", model_name)

    return _STATE["model"]


def _load_model_sync(model_name: str) -> "BGEM3FlagModel":
    """동기 모델 로드 함수 — to_thread 내부에서 실행된다."""
    if not _FLAG_AVAILABLE:
        raise RuntimeError("FlagEmbedding 패키지가 설치되지 않아 BGE-M3를 로드할 수 없습니다.")
    return BGEM3FlagModel(model_name, use_fp16=True)


class BGEM3Embedder:
    """BGE-M3 기반 하이브리드 임베더.

    Dense(1024d) + Sparse 벡터를 동시에 생성하여
    Qdrant 하이브리드 검색에 최적화된 형태로 반환한다.
    """

    name: str = "bge-m3"

    async def embed(self, texts: list[str]) -> list[dict]:
        """텍스트 리스트를 Dense+Sparse 임베딩 딕셔너리 리스트로 변환한다.

        빈 텍스트는 영벡터로 대체하여 Qdrant 업서트 실패를 방지한다.
        """
        if not texts:
            return []

        model = await _ensure_model()
        batch_size = embedding_batch_size()

        # 배치 단위로 처리하여 메모리 과부하 방지
        all_results: list[dict] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_embeddings = await asyncio.to_thread(
                _embed_batch_sync, model, batch
            )
            all_results.extend(batch_embeddings)

        return all_results


def _embed_batch_sync(model: "BGEM3FlagModel", texts: list[str]) -> list[dict]:
    """배치 임베딩 동기 함수 — asyncio.to_thread 내부에서 실행된다.

    BGEM3FlagModel.encode()는 CPU/GPU 계산이므로 별도 스레드에서 실행한다.
    """
    output = model.encode(
        texts,
        batch_size=len(texts),
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,  # ColBERT는 사용하지 않아 비활성화
    )

    dense_vecs = output["dense_vecs"]          # shape: (N, 1024), numpy array
    lexical_weights = output["lexical_weights"]  # list[dict[str, float]]

    results: list[dict] = []
    for i, (dense, sparse_weights) in enumerate(zip(dense_vecs, lexical_weights)):
        # Qdrant SparseVector 형식으로 변환: {indices: list[int], values: list[float]}
        if sparse_weights:
            indices = [int(k) for k in sparse_weights.keys()]
            values = [float(v) for v in sparse_weights.values()]
        else:
            indices, values = [], []

        results.append({
            "dense": dense.tolist(),
            "sparse": {"indices": indices, "values": values},
        })

    return results
