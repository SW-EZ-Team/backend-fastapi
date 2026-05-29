"""검증 결과에 따라 재시도/통과를 라우팅하는 노드."""
from __future__ import annotations

import time

from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.common.ai_bridge import get_current_budget
from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)


async def retry_router_node(state: ExamForgeState) -> dict:
    """실제 재시도가 필요한 경우에만 카운터를 증가시킨다.

    passed/exhausted 경로에서는 카운터를 변경하지 않아
    off-by-one 보고 오류를 방지한다.
    """
    # 상위 노드에서 에러가 전파된 경우 즉시 반환
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: retry_router_node")
    route = route_after_validation(state)
    if route == "retry":
        # 실제 재시도 시에만 카운터 증가
        logger.info("노드 완료: retry_router_node (%.2fs) → retry", time.time() - node_start)
        return {"retry_count": state.get("retry_count", 0) + 1}
    # 통과 또는 소진 시 카운터 유지
    logger.info("노드 완료: retry_router_node (%.2fs) → %s", time.time() - node_start, route)
    return {}


def route_after_validation(state: ExamForgeState) -> str:
    """조건부 엣지 라우팅 함수.

    구조적 실패율 외에 품질 지표 게이트(정확률, 중복 점수)도 함께 확인한다.
    게이트 미달 시 재시도로 라우팅해 품질 기준 미충족 문제 세트의 통과를 방지한다.
    LLM 호출 예산 초과 시에도 추가 재시도를 차단한다.
    """
    # 파이프라인 에러 상태이면 재시도 없이 즉시 종료 경로로 라우팅한다
    if state.get("pipeline_status") == "error":
        logger.warning("route_after_validation: pipeline_status=error — exhausted 경로로 전달")
        return "exhausted"

    # LLM 예산 서킷 브레이커: 예산 소진 시 무조건 종료 경로
    budget = get_current_budget()
    if budget is not None and budget.exceeded:
        logger.warning("LLM 예산 소진 (%d/%d) — 재시도 차단", budget.count, budget.budget)
        return "exhausted"

    failed_ids = state.get("failed_question_ids", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    error_message = state.get("error_message")
    questions = (
        state.get("calibrated_questions", [])
        or state.get("answered_questions", [])
        or state.get("verified_questions", [])
        or state.get("questions", [])
    )
    total = len(questions)

    # 결정적 실패 감지: 에러 메시지가 있고 문제가 비어있으면 재시도해도 동일 결과
    if error_message and total == 0:
        logger.warning("결정적 실패 감지 — 재시도 없이 즉시 종료: %s", error_message)
        return "exhausted"

    # 문제가 하나도 없으면 재생성 또는 종료
    if total == 0:
        _dest = "exhausted" if retry_count >= max_retries else "retry"
        logger.info("route_after_validation: 문제 0건 — %s", _dest)
        return _dest

    # --- 구조적 실패율 기반 판단 ---
    fail_rate = len(failed_ids) / total
    if fail_rate >= 0.1:
        _dest = "exhausted" if retry_count >= max_retries else "retry"
        logger.info("route_after_validation: 실패율 %.1f%% (>= 10%%) — %s", fail_rate * 100, _dest)
        return _dest

    # --- 품질 지표 게이트: 검증 보고서 확인 ---
    validation_report = state.get("validation_report", {})

    # validate_node 이후에는 품질 게이트를 적용하되, 테스트 더블/중간 상태처럼
    # validation_report 자체가 없으면 구조적 실패율만으로 판단한다.
    accuracy_rate = validation_report.get("answer_accuracy_rate")
    if isinstance(accuracy_rate, (int, float)) and accuracy_rate < 0.95:
        _dest = "exhausted" if retry_count >= max_retries else "retry"
        logger.info("route_after_validation: 정확률 %.2f (< 0.95) — %s", accuracy_rate, _dest)
        return _dest

    dedup_score = validation_report.get("dedup_score")
    if isinstance(dedup_score, (int, float)) and dedup_score < 0.8:
        _dest = "exhausted" if retry_count >= max_retries else "retry"
        logger.info("route_after_validation: 중복점수 %.2f (< 0.8) — %s", dedup_score, _dest)
        return _dest

    logger.info(
        "route_after_validation: 모든 게이트 통과 — passed (정확률=%s, 중복=%s, 실패율=%.1f%%)",
        accuracy_rate, dedup_score, fail_rate * 100,
    )
    return "passed"
