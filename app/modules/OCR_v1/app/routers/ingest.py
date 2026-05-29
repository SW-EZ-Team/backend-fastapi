"""PDF 인제스트 라우터 — multipart/form-data 로 PDF 를 받아 파이프라인을 실행한다.

파이프라인 결과(OCRPipelineState 딕셔너리)를 OCRv1IngestResponse 로 변환해 반환한다.
업로드 크기 초과 시 413, 파이프라인 내부 오류 시 500을 반환한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, UploadFile

from ...connector import OCRv1Pipeline
from ...schemas.response import OCRv1IngestResponse, PageSummary

router = APIRouter()


def _build_page_summaries(state: dict) -> list[PageSummary]:
    """파이프라인 상태에서 페이지별 요약 목록을 생성한다.

    quality_scores 를 기준으로 classifications, extractions 와 조합해 반환한다.
    """
    # engine 정보 조회용 추출 결과 인덱스 (page_num → engine)
    engine_map: dict[int, str] = {
        e.get("page_num", 0): e.get("engine", "")
        for e in state.get("extractions", [])
    }
    # 폴백 추출로 덮어쓰기 (폴백이 있으면 실제 사용 엔진)
    for e in state.get("fallback_extractions", []):
        engine_map[e.get("page_num", 0)] = e.get("engine", "")

    # page_type 조회용 분류 결과 인덱스
    type_map: dict[int, str] = {
        c.get("page_num", 0): c.get("page_type", "")
        for c in state.get("classifications", [])
    }

    summaries: list[PageSummary] = []
    for qs in state.get("quality_scores", []):
        pnum = qs.get("page_num", 0)
        summaries.append(PageSummary(
            page_num=pnum,
            page_type=type_map.get(pnum, "unknown"),
            engine=engine_map.get(pnum, "unknown"),
            quality_score=round(qs.get("overall", 0.0), 4),
            passed=qs.get("passed", False),
        ))
    return summaries


def _state_to_response(state: dict) -> OCRv1IngestResponse:
    """OCRPipelineState 딕셔너리를 OCRv1IngestResponse 로 변환한다."""
    return OCRv1IngestResponse(
        status=state.get("pipeline_status", "error"),
        total_pages=state.get("total_pages", 0),
        chunk_count=len(state.get("chunks", [])),
        embedded_count=state.get("embedded_count", 0),
        collection_name=state.get("collection_name", ""),
        pages=_build_page_summaries(state),
        timings={k: round(v, 3) for k, v in state.get("timings", {}).items()},
        error_message=state.get("error_message"),
    )


@router.post("/ingest", response_model=OCRv1IngestResponse, summary="PDF 인제스트")
async def ingest_pdf(
    file: UploadFile,
    collection_name: str = Form(default=""),
) -> OCRv1IngestResponse:
    """PDF 파일을 업로드해 OCR 파이프라인을 실행하고 결과를 반환한다.

    - **file**: PDF 파일 (multipart/form-data)
    - **collection_name**: Qdrant 컬렉션명 (빈 값이면 파일명에서 자동 생성)
    """
    # PDF 파일 형식 검증
    filename = file.filename or "upload.pdf"
    is_pdf_mime = (file.content_type or "").lower() == "application/pdf"
    is_pdf_ext = filename.lower().endswith(".pdf")
    if not (is_pdf_mime or is_pdf_ext):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능합니다.")

    pdf_bytes = await file.read()

    # 파일 크기 제한 검사
    from app.core.constants import MAX_PDF_UPLOAD_SIZE_BYTES
    if len(pdf_bytes) > MAX_PDF_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"파일 크기가 제한({MAX_PDF_UPLOAD_SIZE_BYTES // 1_048_576}MB)을 초과합니다.",
        )

    try:
        pipeline = OCRv1Pipeline()
        state = await pipeline.ingest(pdf_bytes, filename, collection_name)
        return _state_to_response(state)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"OCR 파이프라인 오류: {exc}",
        ) from exc
