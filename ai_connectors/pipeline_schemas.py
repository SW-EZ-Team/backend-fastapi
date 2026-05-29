"""교재 OCR 파이프라인 전용 스키마 (Pydantic v2).

OCR 파이프라인 체인(래스터화 → OCR → 후처리)의 최종 출력 구조를 정의한다.
공통 스키마(OCRDetection, Correction 등)는 schemas.py 에서 import 한다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas import Correction, OCRDetection


class PageResult(BaseModel):
    """파이프라인 단일 페이지 인식 결과."""

    page_num: int = Field(..., ge=1, description="페이지 번호 (1-based)")
    text: str = Field(default="", description="해당 페이지 인식 텍스트")
    detections: list[OCRDetection] = Field(
        default_factory=list,
        description="페이지 내 감지 영역 목록 (bbox + text + confidence)",
    )


class OCRPipelineResult(BaseModel):
    """교재 OCR 파이프라인 최종 출력 스키마.

    파이프라인 체인: PDF 래스터화 → PaddleOCR-VL OCR → Kanana-2 postproc.
    단 하나의 OUT (SRP 준수) — 후처리 완료된 구조화 결과.
    """

    plain_text: str = Field(
        ...,
        description="후처리 완료된 전체 텍스트 (페이지 구분자로 이어붙임)",
    )
    pages: list[PageResult] = Field(
        default_factory=list,
        description="페이지별 인식 결과 목록",
    )
    corrections: list[Correction] = Field(
        default_factory=list,
        description="Kanana 후처리가 교정한 항목 목록",
    )
    timings: dict[str, float] = Field(
        default_factory=dict,
        description="단계별 소요 시간(ms): raster_ms, ocr_ms, postproc_ms",
    )
    rasterizer_backend: str = Field(
        default="unknown",
        description="PDF 래스터화에 사용된 백엔드 (lib-rust 또는 pypdfium2)",
    )
    ocr_model: str = Field(
        default="",
        description="OCR 단계에 사용된 모델 식별자",
    )
    postproc_model: str = Field(
        default="",
        description="후처리 단계에 사용된 모델 식별자",
    )
