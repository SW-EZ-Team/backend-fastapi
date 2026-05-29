"""LangGraph Stage 1 노드 — PDF 페이지 타입 분류.

pypdfium2 를 사용해 각 페이지가 born-digital/scanned/mixed 인지 분류한다.
분류 함수는 동기이므로 asyncio.to_thread 로 감싸서 이벤트 루프 블로킹을 방지한다.
"""
from __future__ import annotations

import asyncio
import logging
import time

from ...quality.classifier import classify_pages
from ...schemas.state import OCRPipelineState, PageClassification

_LOG = logging.getLogger(__name__)


async def classify_pdf(state: OCRPipelineState) -> dict:
    """PDF 전체 페이지를 분류하고 분류 결과를 상태에 저장한다.

    pypdfium2 는 스레드 안전하지 않으므로 asyncio.to_thread 로 별도 스레드에서 실행한다.
    오류 발생 시 pipeline_status 를 "error" 로 설정하고 즉시 반환해 파이프라인이
    에러 상태임을 명확히 드러낸다.
    """
    # 이전 단계에서 오류가 발생한 경우 즉시 반환 — 에러 전파 일관성
    if state.get("pipeline_status") == "error":
        return {}
    t0 = time.perf_counter()
    # .get() 으로 접근해 키 누락 시 기본값으로 안전하게 처리
    _LOG.info("Stage 1: PDF 페이지 분류 시작 — 파일명=%s", state.get("pdf_filename", ""))

    try:
        # pypdfium2 는 동기 API 이므로 별도 스레드에서 실행
        results: list[PageClassification] = await asyncio.to_thread(
            classify_pages, state.get("pdf_bytes", b"")
        )
    except Exception as exc:
        _LOG.exception("PDF 페이지 분류 중 오류 발생")
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "pipeline_status": "error",
            "error_message": f"classify_pdf 오류: {exc}",
            "current_stage": "classify",
            "timings": {**state.get("timings", {}), "classify": elapsed},
        }

    elapsed = round(time.perf_counter() - t0, 3)

    if not results:
        _LOG.warning("Stage 1: 분류 결과 0건 — 빈 PDF이거나 손상된 파일")
        return {
            "classifications": [],
            "total_pages": 0,
            "pipeline_status": "error",
            "error_message": "PDF 페이지 분류 결과 0건 — 파일이 비어있거나 손상됨",
            "current_stage": "classify",
            "timings": {**state.get("timings", {}), "classify": elapsed},
        }

    _LOG.info(
        "Stage 1 완료: %d 페이지 분류, %.3fs 소요",
        len(results),
        elapsed,
    )

    return {
        "classifications": results,
        "total_pages": len(results),
        "current_stage": "classify",
        "timings": {**state.get("timings", {}), "classify": elapsed},
    }
