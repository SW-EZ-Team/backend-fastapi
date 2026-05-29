"""LangGraph Stage 6 노드 — 마크다운 후처리.

헤더/푸터 제거, 하이픈 복원, 단락 병합, 표 정규화, 수식 변환을
각 페이지 마크다운에 순차 적용한다.
"""
from __future__ import annotations

import logging
import time

from ...postprocess import run_all
from ...schemas.state import OCRPipelineState, PageExtraction

_LOG = logging.getLogger(__name__)


async def _postprocess_page(page: PageExtraction) -> PageExtraction:
    """단일 페이지 마크다운에 전체 후처리 파이프라인을 적용한다.

    run_all 은 async 함수이므로 직접 await 한다.
    키 누락 시 안전한 기본값을 사용해 KeyError 를 방지한다.
    """
    # .get() 으로 모든 PageExtraction 필드에 안전하게 접근
    cleaned_md = await run_all(page.get("markdown", ""))
    return PageExtraction(
        page_num=page.get("page_num", 0),
        markdown=cleaned_md,
        tables=page.get("tables", []),
        formulas=page.get("formulas", []),
        engine=page.get("engine", ""),
        llm_corrected=page.get("llm_corrected", False),
    )


async def postprocess(state: OCRPipelineState) -> dict:
    """모든 추출 페이지에 후처리를 적용하고 processed_pages 에 저장한다.

    후처리는 페이지 독립적이므로 순서를 보존하며 순차 실행한다.
    오류 발생 시 pipeline_status 를 "error" 로 설정해 실패를 명시적으로 표현한다.
    """
    # 이전 단계에서 오류가 발생한 경우 즉시 반환 — 에러 전파로 불필요한 처리를 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    t0 = time.perf_counter()
    # .get() 으로 extractions 에 안전하게 접근해 키 누락 시 빈 목록으로 처리
    extractions: list = state.get("extractions", [])
    _LOG.info("Stage 6: 후처리 시작 — %d 페이지", len(extractions))

    # 입력 0건 — 업스트림에서 빈 추출 결과가 전파된 경우
    if not extractions:
        _LOG.warning("Stage 6: 입력 페이지 0건 — 후처리 건너뜀")
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "processed_pages": [],
            "current_stage": "postprocess",
            "pipeline_status": "partial",
            "error_message": "추출된 페이지 0건 — 후처리 입력 없음",
            "timings": {**state.get("timings", {}), "postprocess": elapsed},
        }

    processed: list[PageExtraction] = []
    degraded_count = 0
    for page in extractions:
        try:
            processed_page = await _postprocess_page(page)
            processed.append(processed_page)
        except Exception as exc:
            _LOG.warning(
                "페이지 %d 후처리 실패 — 원본 유지: %s",
                page.get("page_num", 0), exc,
            )
            processed.append(page)
            degraded_count += 1

    elapsed = round(time.perf_counter() - t0, 3)
    if degraded_count > 0:
        _LOG.warning(
            "Stage 6: %d/%d 페이지 후처리 실패 — 원본 유지됨",
            degraded_count, len(extractions),
        )
    _LOG.info("Stage 6 완료: %d 페이지 처리, %.3fs 소요", len(processed), elapsed)

    result: dict = {
        "processed_pages": processed,
        "current_stage": "postprocess",
        "timings": {**state.get("timings", {}), "postprocess": elapsed},
    }
    # 후처리 실패 페이지가 있으면 partial 상태로 품질 저하를 명시한다
    if degraded_count > 0:
        result["pipeline_status"] = "partial"
        result["error_message"] = f"후처리 실패 {degraded_count}/{len(extractions)} 페이지 — 원본 유지"
    return result
