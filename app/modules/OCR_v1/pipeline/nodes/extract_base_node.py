"""LangGraph Stage 2 노드 — 기본 OCR 추출.

레지스트리에서 기본(primary) OCR 엔진을 가져와 PDF 전체를 추출한다.
엔진은 비동기 API 를 제공하므로 직접 await 한다.
"""
from __future__ import annotations

import logging
import time

from ...registry import get_engine
from ...schemas.state import OCRPipelineState, PageExtraction

_LOG = logging.getLogger(__name__)


async def extract_base(state: OCRPipelineState) -> dict:
    """기본 OCR 엔진으로 PDF 를 추출하고 페이지별 결과를 상태에 저장한다.

    레지스트리의 primary 엔진을 사용하며, 엔진 미등록이나 추출 오류 발생 시
    pipeline_status 를 "error" 로 설정해 파이프라인 실패를 명시적으로 표현한다.
    """
    # 이전 단계에서 오류가 발생한 경우 즉시 반환 — 에러 전파로 불필요한 처리를 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    t0 = time.perf_counter()
    _LOG.info("Stage 2: 기본 OCR 추출 시작")

    try:
        engine = get_engine()
        _LOG.info("사용 엔진: %s", engine.name)
        # .get() 으로 접근해 pdf_bytes 키 누락 시 빈 bytes 로 처리 (엔진이 오류를 발생시킴)
        results: list[PageExtraction] = await engine.extract(state.get("pdf_bytes", b""))
    except Exception as exc:
        _LOG.exception("기본 OCR 추출 중 오류 발생")
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "pipeline_status": "error",
            "error_message": f"extract_base 오류: {exc}",
            "current_stage": "extract",
            "timings": {**state.get("timings", {}), "extract": elapsed},
        }

    elapsed = round(time.perf_counter() - t0, 3)

    if not results:
        _LOG.warning("Stage 2: 추출 결과 0건 — 빈 PDF 또는 엔진 무응답")
        return {
            "extractions": [],
            "pipeline_status": "error",
            "error_message": "OCR 추출 결과 0건 — PDF가 비어있거나 엔진이 페이지를 인식하지 못함",
            "current_stage": "extract",
            "timings": {**state.get("timings", {}), "extract": elapsed},
        }

    _LOG.info(
        "Stage 2 완료: %d 페이지 추출, %.3fs 소요",
        len(results),
        elapsed,
    )

    return {
        "extractions": results,
        "current_stage": "extract",
        "timings": {**state.get("timings", {}), "extract": elapsed},
    }
