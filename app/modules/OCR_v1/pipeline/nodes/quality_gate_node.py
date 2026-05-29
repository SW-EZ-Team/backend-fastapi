"""LangGraph Stage 4 노드 — 품질 게이트 + 라우팅 결정.

각 페이지 추출물에 대해 네 가지 품질 지표를 계산하고 종합 점수로 통과 여부를 판정한다.
route_after_quality 는 조건부 엣지 라우터로 파이프라인 분기를 결정한다.
"""
from __future__ import annotations

import logging
import time

from ...quality.aggregate import aggregate_page_quality
from ...quality.char_corruption import score_char_corruption
from ...quality.formula_check import score_formula_preservation
from ...quality.reading_order import score_reading_order
from ...quality.table_integrity import score_table_integrity
from ...schemas.state import OCRPipelineState, PageExtraction, QualityScore

_LOG = logging.getLogger(__name__)


def _score_page(page: PageExtraction) -> QualityScore:
    """단일 페이지 추출 결과에 대한 품질 점수를 계산한다.

    각 품질 함수는 (score, reason) 튜플을 반환하므로 첫 번째 요소만 사용한다.
    키 누락 시 안전한 기본값을 사용해 KeyError 를 방지한다.
    """
    # .get() 으로 접근해 TypedDict 키가 없어도 KeyError 없이 처리
    markdown: str = page.get("markdown", "")
    tables: list = page.get("tables", [])
    formulas: list = page.get("formulas", [])

    # 각 지표 함수는 (float, str) 튜플 반환 — score 값만 추출
    char, _ = score_char_corruption(markdown)
    reading, _ = score_reading_order(markdown)
    table, _ = score_table_integrity(markdown, tables)
    formula, _ = score_formula_preservation(markdown, formulas)

    overall, passed = aggregate_page_quality(char, reading, table, formula)

    return QualityScore(
        page_num=page.get("page_num", 0),
        char_corruption=char,
        reading_order=reading,
        table_integrity=table,
        formula_preservation=formula,
        overall=overall,
        passed=passed,
    )


async def quality_gate(state: OCRPipelineState) -> dict:
    """모든 추출 페이지의 품질을 평가하고 통과/실패 목록을 구분한다.

    품질 평가는 CPU 연산이므로 별도 스레드 없이 동기로 실행한다.
    오류 발생 시 pipeline_status 를 "error" 로 설정해 명시적으로 실패를 표현한다.
    """
    # 이전 단계에서 오류가 발생한 경우 즉시 반환 — 에러 전파로 불필요한 처리를 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    t0 = time.perf_counter()
    # .get() 으로 접근해 extractions 키 누락 시 빈 목록으로 안전하게 처리
    extractions: list = state.get("extractions", [])
    _LOG.info("Stage 4: 품질 게이트 평가 시작 — %d 페이지", len(extractions))

    # 입력 0건 — 업스트림에서 추출 결과가 없는 경우 조기 종료
    if not extractions:
        _LOG.warning("Stage 4: 추출 결과 0건 — 품질 평가 건너뜀")
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "quality_scores": [],
            "passed_pages": [],
            "failed_pages": [],
            "current_stage": "quality_gate",
            "pipeline_status": "partial",
            "error_message": "추출 결과 0건 — 품질 평가 입력 없음",
            "timings": {**state.get("timings", {}), "quality_gate": elapsed},
        }

    scores: list[QualityScore] = []
    for page in extractions:
        try:
            scores.append(_score_page(page))
        except Exception as exc:
            _LOG.warning(
                "페이지 %d 품질 평가 실패 — 기본 실패 점수 사용: %s",
                page.get("page_num", 0), exc,
            )
            scores.append(QualityScore(
                page_num=page.get("page_num", 0),
                char_corruption=1.0,
                reading_order=0.0,
                table_integrity=0.0,
                formula_preservation=0.0,
                overall=0.0,
                passed=False,
            ))

    # .get() 으로 QualityScore 딕셔너리 필드에 안전하게 접근
    passed_pages = [s.get("page_num", 0) for s in scores if s.get("passed", False)]
    failed_pages = [s.get("page_num", 0) for s in scores if not s.get("passed", False)]

    elapsed = round(time.perf_counter() - t0, 3)
    _LOG.info(
        "Stage 4 완료: 통과=%d, 실패=%d, %.3fs 소요",
        len(passed_pages),
        len(failed_pages),
        elapsed,
    )

    return {
        "quality_scores": scores,
        "passed_pages": passed_pages,
        "failed_pages": failed_pages,
        "current_stage": "quality_gate",
        "timings": {**state.get("timings", {}), "quality_gate": elapsed},
    }


def route_after_quality(state: OCRPipelineState) -> str:
    """품질 게이트 결과에 따라 다음 단계를 결정하는 조건부 엣지 라우터.

    - "pass"     : 모든 페이지 통과 → 후처리로 직행
    - "partial"  : 일부 페이지 실패 → 폴백 엔진 재추출 후 후처리
    - "fail_all" : 전 페이지 실패 → 최선의 결과로 후처리 진행
    """
    # 이전 단계 에러 발생 시 즉시 전체 실패로 라우팅 — 정상 경로 판단을 방지한다
    if state.get("pipeline_status") == "error":
        _LOG.info("품질 라우팅: fail_all (pipeline_status=error)")
        return "fail_all"

    passed = state.get("passed_pages", [])
    failed = state.get("failed_pages", [])

    # 추출 결과가 없으면 통과할 페이지도 없다 — 전체 실패로 처리
    if not passed and not failed:
        _LOG.info("품질 라우팅: fail_all (추출 결과 없음)")
        return "fail_all"

    if not failed:
        _LOG.info("품질 라우팅: pass (전 페이지 통과)")
        return "pass"

    if not passed:
        _LOG.info("품질 라우팅: fail_all (전 페이지 실패)")
        return "fail_all"

    _LOG.info("품질 라우팅: partial (통과=%d, 실패=%d)", len(passed), len(failed))
    return "partial"
