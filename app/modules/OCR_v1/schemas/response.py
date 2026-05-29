"""OCR_v1 API 응답 스키마 — Pydantic v2 기반.

클라이언트가 받는 최종 직렬화 형식이므로 명세 변경 시 하위 호환성을 주의한다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PageSummary(BaseModel):
    """인제스트 결과의 개별 페이지 요약 정보."""

    page_num: int = Field(..., description="1-based 페이지 번호")
    page_type: str = Field(..., description="born-digital | scanned | mixed")
    engine: str = Field(..., description="사용된 OCR 엔진명")
    quality_score: float = Field(..., description="종합 품질 점수 (0.0~1.0)")
    passed: bool = Field(..., description="품질 게이트 통과 여부")


class OCRv1IngestResponse(BaseModel):
    """PDF 인제스트 완료 응답.

    클라이언트는 status 와 embedded_count 로 성공 여부와 결과 규모를 확인한다.
    """

    status: str = Field(..., description="done | error")
    total_pages: int = Field(..., description="PDF 전체 페이지 수")
    chunk_count: int = Field(..., description="생성된 청크 수")
    embedded_count: int = Field(..., description="실제 임베딩·저장된 청크 수")
    collection_name: str = Field(..., description="저장된 Qdrant 컬렉션명")
    pages: list[PageSummary] = Field(default_factory=list, description="페이지별 처리 요약")
    timings: dict[str, float] = Field(default_factory=dict, description="Stage 별 소요 시간(초)")
    error_message: str | None = Field(default=None, description="오류 발생 시 메시지")


class SearchHit(BaseModel):
    """단일 검색 결과 항목."""

    chunk_id: str = Field(..., description="청크 고유 식별자")
    text: str = Field(..., description="청크 본문 텍스트")
    score: float = Field(..., description="리랭킹 후 관련도 점수")
    section_title: str = Field(..., description="청크가 속한 섹션 제목")
    page_nums: list[int] = Field(default_factory=list, description="원본 페이지 번호 목록")


class OCRv1SearchResponse(BaseModel):
    """RAG 하이브리드 검색 결과 응답."""

    query: str = Field(..., description="입력 검색 쿼리")
    hits: list[SearchHit] = Field(default_factory=list, description="상위 검색 결과 목록")
    total_found: int = Field(..., description="리랭킹 전 초기 검색 결과 총 수")
