"""OCR_v1 파이프라인 진입점 — 외부 호출자는 이 클래스만 사용한다.

내부 LangGraph 그래프와 검색 모듈을 숨기고 단일 인터페이스를 제공한다.
backend-fastapi 이식 시에도 이 파일의 공개 API 는 변경되지 않는다.
"""
from __future__ import annotations

import logging

from .schemas.state import OCRPipelineState

_LOG = logging.getLogger(__name__)


class OCRv1Pipeline:
    """OCR v1 LangGraph 파이프라인 래퍼.

    인스턴스를 생성한 뒤 ingest() 또는 search() 를 직접 호출한다.
    모든 내부 의존성은 지연 import 로 처리해 모듈 로드 시 사이드이펙트를 최소화한다.
    """

    name: str = "ocr-v1-pipeline"

    async def ingest(
        self,
        pdf_bytes: bytes,
        filename: str,
        collection_name: str = "",
    ) -> dict:
        """PDF 인제스트 — 전체 LangGraph 파이프라인을 실행한다.

        반환값은 OCRPipelineState 와 동일한 딕셔너리 구조를 갖는다.
        """
        from .pipeline.graph import get_compiled_graph

        # 컬렉션명 미지정 시 파일명에서 자동 생성
        coll = collection_name or filename.rsplit(".", 1)[0].replace(" ", "_")
        _LOG.info("인제스트 시작: %s → 컬렉션=%s", filename, coll)

        initial_state: OCRPipelineState = {
            "pdf_bytes": pdf_bytes,
            "pdf_filename": filename,
            "total_pages": 0,
            "classifications": [],
            "extractions": [],
            "quality_scores": [],
            "passed_pages": [],
            "failed_pages": [],
            "fallback_extractions": [],
            "processed_pages": [],
            "chunks": [],
            "collection_name": coll,
            "embedded_count": 0,
            "embedding_model": "",
            "current_stage": "init",
            "pipeline_status": "running",
            "error_message": None,
            "timings": {},
        }

        graph = get_compiled_graph()
        result = await graph.ainvoke(initial_state)
        _LOG.info("인제스트 완료: 상태=%s, 청크=%d", result["pipeline_status"], len(result["chunks"]))
        return result

    async def search(
        self,
        query: str,
        collection_name: str,
        top_k: int = 5,
    ) -> list[dict]:
        """RAG 하이브리드 검색 — 임베딩+희소 검색 후 리랭킹 결과를 반환한다."""
        from .search import hybrid_search

        _LOG.info("검색 시작: query='%.50s', collection=%s, top_k=%d", query, collection_name, top_k)
        return await hybrid_search(query, collection_name, top_k)

    def supports(self, feature: str) -> bool:
        """파이프라인이 특정 기능을 지원하는지 반환한다."""
        return feature in {"pdf_ingest", "rag_search", "hybrid", "korean"}
