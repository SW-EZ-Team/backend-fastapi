"""LangGraph Stage 5 노드 — 폴백 엔진 재추출.

품질 게이트에서 실패한 페이지만 폴백 엔진으로 재추출한다.
재추출 결과로 기존 extractions 의 실패 페이지를 교체해 다음 단계에 전달한다.
"""
from __future__ import annotations

import logging
import time

from ...registry import get_fallback_engine
from ...schemas.state import OCRPipelineState, PageExtraction

_LOG = logging.getLogger(__name__)


def _build_page_index(extractions: list[PageExtraction]) -> dict[int, int]:
    """page_num → extractions 리스트 인덱스 역방향 맵을 생성한다.

    실패 페이지를 빠르게 교체하기 위해 인덱스를 미리 계산한다.
    키 누락 시 0 을 기본값으로 사용해 KeyError 를 방지한다.
    """
    return {page.get("page_num", 0): idx for idx, page in enumerate(extractions)}


async def fallback(state: OCRPipelineState) -> dict:
    """실패 페이지를 폴백 엔진으로 재추출하고 extractions 를 병합한다.

    failed_pages 가 없으면 아무 작업도 하지 않고 통과한다.
    재추출 결과는 fallback_extractions 에도 별도 보관해 감사 목적으로 활용한다.
    """
    # 이전 단계에서 오류가 발생한 경우 즉시 반환 — 에러 전파로 불필요한 처리를 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    t0 = time.perf_counter()
    failed_pages = state.get("failed_pages", [])

    if not failed_pages:
        _LOG.info("Stage 5: 실패 페이지 없음 — 폴백 건너뜀")
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "fallback_extractions": [],
            "current_stage": "fallback",
            "timings": {**state.get("timings", {}), "fallback": elapsed},
        }

    _LOG.info("Stage 5: 폴백 재추출 시작 — 대상 페이지=%s", failed_pages)

    try:
        fallback_engine = get_fallback_engine()
        _LOG.info("폴백 엔진: %s", fallback_engine.name)

        # 0-based 인덱스로 변환해 엔진에 전달
        page_indices = [pn - 1 for pn in failed_pages]
        fallback_results: list[PageExtraction] = await fallback_engine.extract(
            # .get() 으로 pdf_bytes 에 안전하게 접근
            state.get("pdf_bytes", b""), pages=page_indices
        )
    except Exception as exc:
        _LOG.warning("폴백 재추출 실패 — 기존 추출 결과 유지 (partial): %s", exc)
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "fallback_extractions": [],
            "pipeline_status": "partial",
            "error_message": f"폴백 재추출 실패: {exc}",
            "current_stage": "fallback",
            "timings": {**state.get("timings", {}), "fallback": elapsed},
        }

    # 폴백 요청은 했지만 재추출 결과가 0건인 경우 — 품질 저하를 명시적으로 표시
    if not fallback_results:
        _LOG.warning(
            "Stage 5: %d 페이지 폴백 요청했으나 재추출 결과 0건",
            len(failed_pages),
        )
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "fallback_extractions": [],
            "current_stage": "fallback",
            "pipeline_status": "partial",
            "error_message": f"폴백 재추출 결과 0건 — 실패 페이지 {len(failed_pages)}건 원본 유지",
            "timings": {**state.get("timings", {}), "fallback": elapsed},
        }

    # .get() 으로 extractions 에 안전하게 접근해 실패 페이지를 폴백 결과로 교체
    merged = list(state.get("extractions", []))
    page_index_map = _build_page_index(merged)

    for fb_page in fallback_results:
        # .get() 으로 폴백 결과 page_num 에 안전하게 접근
        pn = fb_page.get("page_num", 0)
        if pn in page_index_map:
            merged[page_index_map[pn]] = fb_page

    elapsed = round(time.perf_counter() - t0, 3)
    _LOG.info(
        "Stage 5 완료: %d 페이지 재추출, %.3fs 소요",
        len(fallback_results),
        elapsed,
    )

    return {
        "extractions": merged,
        "fallback_extractions": fallback_results,
        "current_stage": "fallback",
        "timings": {**state.get("timings", {}), "fallback": elapsed},
    }
