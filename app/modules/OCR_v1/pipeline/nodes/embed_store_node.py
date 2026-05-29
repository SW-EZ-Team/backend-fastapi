"""LangGraph Stage 8 노드 — 임베딩 + 벡터 저장소 업서트.

청크 텍스트를 BGE-M3 임베더로 변환하고 Qdrant 에 업서트한다.
배치 처리는 임베더 내부에서 수행하며 이 노드는 흐름 조율에 집중한다.
"""
from __future__ import annotations

import logging
import time

from ... import config as cfg
from ...registry import get_embedder, get_store
from ...schemas.state import ChunkRecord, OCRPipelineState

_LOG = logging.getLogger(__name__)


def _build_point(chunk: ChunkRecord, embedding: dict, idx: int) -> dict:
    """청크와 임베딩 벡터를 Qdrant PointStruct 입력 딕셔너리로 변환한다.

    id 는 chunk_id 의 첫 15자리를 16진수로 변환해 Qdrant 정수 ID 로 사용한다.
    비-16진수 chunk_id 는 idx 폴백으로 안전하게 처리한다.
    """
    chunk_id = chunk.get("chunk_id", "")
    try:
        point_id = int(chunk_id[:15], 16) if chunk_id else idx
    except ValueError:
        # chunk_id 가 16진수 형식이 아닌 경우 인덱스를 ID 로 사용
        _LOG.warning("chunk_id %r 이 16진수가 아님 — idx=%d 폴백", chunk_id, idx)
        point_id = idx

    payload = {
        "chunk_id": chunk_id,
        "text": chunk.get("text", ""),
        "token_count": chunk.get("token_count", 0),
        "section_title": chunk.get("section_title", ""),
        "section_level": chunk.get("section_level", 0),
        "page_nums": chunk.get("page_nums", []),
        "tables": chunk.get("tables", []),
        "formulas": chunk.get("formulas", []),
    }

    return {
        "id": point_id,
        "dense": embedding.get("dense"),
        "sparse": embedding.get("sparse"),
        "payload": payload,
    }


async def embed_store(state: OCRPipelineState) -> dict:
    """청크를 임베딩하고 벡터 저장소에 업서트한다.

    컬렉션이 없으면 자동 생성한다.
    오류 발생 시 pipeline_status 를 "error" 로 설정해 실패를 명시적으로 표현한다.
    """
    # 이전 단계에서 오류가 발생한 경우 즉시 반환 — 에러 전파로 불필요한 처리를 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    t0 = time.perf_counter()

    try:
        # try 블록 안에서 접근해 KeyError 를 except 로 통일 처리
        chunks: list = state.get("chunks", [])
        collection: str = state.get("collection_name", "")

        # 컬렉션명 누락은 오류이므로 명시적으로 검증
        if not collection:
            raise ValueError("collection_name 이 비어 있어 업서트를 진행할 수 없다")

        # 청크가 없으면 조기 종료 — 업스트림 오류 경로와 정상 빈 문서를 로그로 구분
        if not chunks:
            elapsed = round(time.perf_counter() - t0, 3)
            # 업스트림 오류 감지: current_stage 외에 추가 지표를 확인해 오판을 방지한다
            # - current_stage 가 노드 통과 후 덮어씌워져도 품질 실패 흔적이 남아 있다
            upstream_stage = state.get("current_stage", "")
            quality_scores = state.get("quality_scores", [])
            failed_pages = [
                p for p in quality_scores
                if isinstance(p, dict) and not p.get("passed", False)
            ] if isinstance(quality_scores, list) else []
            has_upstream_failure = (
                upstream_stage in ("quality_gate", "fail_all", "error")
                or bool(failed_pages)
                or state.get("pipeline_status") == "partial"
            )
            if has_upstream_failure:
                _LOG.warning(
                    "Stage 8: 업스트림 품질 실패 후 청크 0건 — 빈 결과로 완료 "
                    "(stage=%s, failed_pages=%d)",
                    upstream_stage, len(failed_pages),
                )
            else:
                _LOG.warning("Stage 8: 업스트림 실패 없이 청크 0건 — 빈 문서 또는 청킹 이상")
            status = "partial"
            result = {
                "embedded_count": 0,
                "embedding_model": "",
                "current_stage": "embed_store",
                "pipeline_status": status,
                "timings": {**state.get("timings", {}), "embed_store": elapsed},
            }
            if has_upstream_failure:
                result["error_message"] = (
                    f"업스트림 품질 실패 후 청크 0건 — "
                    f"stage={upstream_stage}, failed_pages={len(failed_pages)}"
                )
            return result

        _LOG.info(
            "Stage 8: 임베딩 + 업서트 시작 — %d 청크, 컬렉션=%s",
            len(chunks),
            collection,
        )

        embedder = get_embedder()
        store = get_store()

        # 컬렉션 없으면 생성
        await store.ensure_collection(collection)

        # 청크 텍스트 전체를 한 번에 임베딩 (내부 배치 처리)
        texts = [c.get("text", "") for c in chunks]
        embeddings = await embedder.embed(texts)

        # 임베딩 수와 청크 수 일치 검증 — 불일치 시 경고 후 짧은 쪽까지만 처리
        has_mismatch = len(embeddings) != len(chunks)
        if has_mismatch:
            _LOG.warning(
                "임베딩 수(%d)와 청크 수(%d) 불일치 — 짧은 쪽 기준 처리",
                len(embeddings), len(chunks),
            )

        # 포인트 딕셔너리 목록 구성 — 임베딩이 dict 가 아닌 경우 빈 dict 로 대체
        points = [
            _build_point(chunk, emb if isinstance(emb, dict) else {}, idx)
            for idx, (chunk, emb) in enumerate(zip(chunks, embeddings))
        ]

        # Qdrant 에 일괄 업서트
        upserted = await store.upsert(collection, points)

    except Exception as exc:
        _LOG.exception("임베딩·업서트 중 오류 발생")
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "pipeline_status": "error",
            "error_message": f"embed_store 오류: {exc}",
            "current_stage": "embed_store",
            "timings": {**state.get("timings", {}), "embed_store": elapsed},
        }

    elapsed = round(time.perf_counter() - t0, 3)
    try:
        model_name = cfg.embedding_model()
    except Exception as exc:
        _LOG.warning("임베딩 모델명 조회 실패 — 'unknown' 사용: %s", exc)
        model_name = "unknown"
    _LOG.info(
        "Stage 8 완료: %d 청크 업서트, 모델=%s, %.3fs 소요",
        upserted,
        model_name,
        elapsed,
    )

    result: dict = {
        "embedded_count": upserted,
        "embedding_model": model_name,
        "current_stage": "embed_store",
        "pipeline_status": "partial" if has_mismatch else "done",
        "timings": {**state.get("timings", {}), "embed_store": elapsed},
    }
    if has_mismatch:
        result["error_message"] = (
            f"임베딩 수({len(embeddings)})와 청크 수({len(chunks)}) 불일치 — "
            f"짧은 쪽({min(len(embeddings), len(chunks))}) 기준 처리"
        )
    return result
