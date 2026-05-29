"""OCR_v1 API 요청 스키마 — Pydantic v2 기반.

FastAPI 라우터가 이 스키마를 직접 참조하므로 외부 의존성이 없어야 한다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class OCRv1IngestRequest(BaseModel):
    """PDF 인제스트 요청 스키마.

    multipart/form-data 로 PDF 파일을 받고, 선택적으로 컬렉션명을 지정한다.
    collection_name 이 비면 파일명 기반으로 자동 생성된다.
    """

    collection_name: str = Field(
        default="",
        description="Qdrant 컬렉션명 (비면 파일명 기반 자동 생성)",
        max_length=128,
    )


class OCRv1SearchRequest(BaseModel):
    """RAG 하이브리드 검색 요청 스키마.

    query 와 collection_name 은 필수값이며,
    top_k 는 최종 반환할 상위 결과 수를 결정한다.
    """

    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="검색 쿼리 문자열",
    )
    collection_name: str = Field(
        ...,
        description="검색 대상 Qdrant 컬렉션명",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="반환할 최상위 결과 수 (1~50)",
    )
