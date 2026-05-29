"""LangGraph Stage 3 노드 — LLM 사후 교정.

config 에서 LLM 모델명이 지정된 경우에만 교정을 실행한다.
표나 수식을 포함하고 엔진이 llm_correction 을 지원하는 페이지만 재추출한다.
"""
from __future__ import annotations

import logging
import time

from ... import config as cfg
from ...registry import get_engine
from ...schemas.state import OCRPipelineState, PageExtraction

_LOG = logging.getLogger(__name__)


def _needs_llm_correction(page: PageExtraction) -> bool:
    """LLM 교정이 필요한 페이지인지 판단한다.

    표 또는 수식이 하나라도 있는 페이지를 교정 대상으로 선정한다.
    키 누락 시 빈 목록을 기본값으로 사용해 KeyError 를 방지한다.
    """
    return bool(page.get("tables", []) or page.get("formulas", []))


async def _correct_single_page(
    engine: object,
    pdf_bytes: bytes,
    page: PageExtraction,
) -> PageExtraction:
    """단일 페이지를 LLM use_llm=True 옵션으로 재추출한다.

    재추출 결과가 없으면 원본 페이지를 그대로 반환한다.
    """
    # .get() 으로 page_num 에 안전하게 접근
    page_num: int = page.get("page_num", 0)
    # 1-based 페이지 번호를 0-based 인덱스로 변환해 엔진에 전달
    corrected_pages = await engine.extract(
        pdf_bytes, pages=[page_num - 1], use_llm=True
    )
    if corrected_pages:
        result = corrected_pages[0]
        # .get() 으로 재추출 결과 필드에 안전하게 접근
        return PageExtraction(
            page_num=page_num,
            markdown=result.get("markdown", ""),
            tables=result.get("tables", []),
            formulas=result.get("formulas", []),
            engine=result.get("engine", ""),
            llm_corrected=True,
        )
    # 재추출 실패 시 원본 유지
    return page


async def llm_correct(state: OCRPipelineState) -> dict:
    """LLM 교정 대상 페이지를 재추출하고 extractions 를 갱신한다.

    LLM 모델명이 비어 있거나 엔진이 llm_correction 을 지원하지 않으면 통과한다.
    """
    # 이전 단계에서 오류가 발생한 경우 즉시 반환 — 에러 전파로 불필요한 처리를 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    t0 = time.perf_counter()
    try:
        llm_model = cfg.marker_use_llm_model()
    except Exception as exc:
        _LOG.warning("LLM 모델 설정 조회 실패 — 교정 비활성: %s", exc)
        llm_model = ""

    # LLM 교정 비활성 — 추출 결과를 그대로 전달
    if not llm_model:
        _LOG.info("Stage 3: LLM 교정 비활성화 (OCR_V1_MARKER_USE_LLM_MODEL 미설정) — 통과")
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "current_stage": "llm_correct",
            "timings": {**state.get("timings", {}), "llm_correct": elapsed},
        }

    _LOG.info("Stage 3: LLM 교정 시작 — 모델=%s", llm_model)

    try:
        engine = get_engine()
        # 엔진이 llm_correction 기능을 지원하는지 확인
        if not engine.supports("llm_correction"):
            _LOG.info("엔진 '%s' 는 llm_correction 미지원 — 통과", engine.name)
            elapsed = round(time.perf_counter() - t0, 3)
            return {
                "current_stage": "llm_correct",
                "timings": {**state.get("timings", {}), "llm_correct": elapsed},
            }

        updated: list[PageExtraction] = []
        for page in state.get("extractions", []):
            if _needs_llm_correction(page) and not page.get("llm_corrected", False):
                try:
                    corrected = await _correct_single_page(
                        engine, state.get("pdf_bytes", b""), page
                    )
                    updated.append(corrected)
                except Exception as page_exc:
                    _LOG.warning(
                        "페이지 %d LLM 교정 실패 — 원본 유지: %s",
                        page.get("page_num", 0), page_exc,
                    )
                    updated.append(page)
            else:
                updated.append(page)

    except Exception as exc:
        _LOG.exception("LLM 교정 중 오류 발생")
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "pipeline_status": "error",
            "error_message": f"llm_correct 오류: {exc}",
            "current_stage": "llm_correct",
            "timings": {**state.get("timings", {}), "llm_correct": elapsed},
        }

    elapsed = round(time.perf_counter() - t0, 3)
    # .get() 으로 llm_corrected 에 안전하게 접근
    corrected_count = sum(1 for p in updated if p.get("llm_corrected", False))
    _LOG.info("Stage 3 완료: %d 페이지 교정, %.3fs 소요", corrected_count, elapsed)

    return {
        "extractions": updated,
        "current_stage": "llm_correct",
        "timings": {**state.get("timings", {}), "llm_correct": elapsed},
    }
