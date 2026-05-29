"""스키마 패키지 — 상태, 요청, 응답 타입을 한 곳에서 re-export한다."""
from __future__ import annotations

from .state import (
    ChunkRecord,
    OCRPipelineState,
    PageClassification,
    PageExtraction,
    QualityScore,
)
from .request import OCRv1IngestRequest, OCRv1SearchRequest
from .response import (
    OCRv1IngestResponse,
    OCRv1SearchResponse,
    PageSummary,
    SearchHit,
)

__all__ = [
    # 상태 타입
    "PageClassification",
    "PageExtraction",
    "QualityScore",
    "ChunkRecord",
    "OCRPipelineState",
    # 요청
    "OCRv1IngestRequest",
    "OCRv1SearchRequest",
    # 응답
    "PageSummary",
    "OCRv1IngestResponse",
    "SearchHit",
    "OCRv1SearchResponse",
]
