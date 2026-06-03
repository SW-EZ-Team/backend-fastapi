"""검증 결과에 따라 재시도/통과를 라우팅하는 노드."""
from __future__ import annotations

import time

from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.common.ai_bridge import get_current_budget
from app.modules.ExamForge_V1.common.config import verification_advisory_enabled
from app.modules.ExamForge_V1.common.logger import get_logger
from app.modules.ExamForge_V1.common.verification_status import (
    advisory_filtered_failed_ids,
    has_parse_failed_majority,
    verification_counts,
)

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
    verification_advisory = _is_verification_advisory(state)
    failed_ids = advisory_filtered_failed_ids(
        state.get("failed_question_ids", []),
        questions,
        verification_advisory=verification_advisory,
    )
    if verification_advisory and verification_counts(questions)["failed"] > 0:
        logger.warning(
            "route_after_validation: 검증 advisory 모드 — genuine fail은 재시도율에서 제외"
        )

    # 결정적 실패 감지: 에러 메시지가 있고 문제가 비어있으면 재시도해도 동일 결과
    if error_message and total == 0:
        logger.warning("결정적 실패 감지 — 재시도 없이 즉시 종료: %s", error_message)
        return "exhausted"

    # 문제가 하나도 없으면 재생성 또는 종료
    if total == 0:
        _dest = "exhausted" if retry_count >= max_retries else "retry"
        logger.info("route_after_validation: 문제 0건 — %s", _dest)
        return _dest

    # --- plan-first P1-B: 개수 충족 하드 게이트 ---
    # validate_node가 보고한 missing_count(개수 부족·슬롯 누락)가 1 이상이면
    # 구조 실패율과 무관하게 retry/exhausted로 라우팅한다.
    # "개수만 부족한데 passed로 출고되는" 결함을 차단한다.
    validation_report_early = state.get("validation_report", {})
    missing_count = validation_report_early.get("missing_count")
    if isinstance(missing_count, int) and missing_count > 0:
        _dest = "exhausted" if retry_count >= max_retries else "retry"
        logger.info(
            "route_after_validation: 개수 부족 missing_count=%d — %s",
            missing_count, _dest,
        )
        return _dest

    # plan-first P1-B: 정답 위치 분포 불일치도 게이트로 승격
    if validation_report_early.get("answer_position_mismatch") is True:
        _dest = "exhausted" if retry_count >= max_retries else "retry"
        logger.info("route_after_validation: 정답 위치 분포 불일치 — %s", _dest)
        return _dest

    # --- 구조적 실패율 기반 판단 ---
    fail_rate = len(failed_ids) / total
    if fail_rate >= 0.1:
        _dest = "exhausted" if retry_count >= max_retries else "retry"
        logger.info("route_after_validation: 실패율 %.1f%% (>= 10%%) — %s", fail_rate * 100, _dest)
        return _dest

    # --- 품질 지표 게이트: 검증 보고서 확인 ---
    validation_report = state.get("validation_report", {})
    parse_failed_advisory = verification_advisory or (
        has_parse_failed_majority(questions)
        and verification_counts(questions)["failed"] == 0
        and not failed_ids
    )

    # validate_node 이후에는 품질 게이트를 적용하되, 테스트 더블/중간 상태처럼
    # validation_report 자체가 없으면 구조적 실패율만으로 판단한다.
    accuracy_rate = validation_report.get("answer_accuracy_rate")
    if isinstance(accuracy_rate, (int, float)) and accuracy_rate < 0.95 and not parse_failed_advisory:
        _dest = "exhausted" if retry_count >= max_retries else "retry"
        logger.info("route_after_validation: 정확률 %.2f (< 0.95) — %s", accuracy_rate, _dest)
        return _dest

    dedup_score = validation_report.get("dedup_score")
    if isinstance(dedup_score, (int, float)):
        # plan-first: 블루프린트가 적용된 경우 concept_key 사전 유일화로
        # 구조적으로 중복 0이 보장돼야 한다 → 게이트를 1.0으로 상향한다.
        # 블루프린트 미적용(answer_position_plan 없음) 경우 기존 0.8 유지.
        questions = (
            state.get("calibrated_questions", [])
            or state.get("answered_questions", [])
            or state.get("verified_questions", [])
            or state.get("questions", [])
        )
        plan = state.get("exam_plan", {})
        has_blueprint = bool(plan.get("answer_position_plan"))
        dedup_threshold = 1.0 if has_blueprint else 0.8
        if dedup_score < dedup_threshold:
            _dest = "exhausted" if retry_count >= max_retries else "retry"
            logger.info(
                "route_after_validation: 중복점수 %.2f (< %.1f, blueprint=%s) — %s",
                dedup_score, dedup_threshold, has_blueprint, _dest,
            )
            return _dest

    logger.info(
        "route_after_validation: 모든 게이트 통과 — passed (정확률=%s, 중복=%s, 실패율=%.1f%%)",
        accuracy_rate, dedup_score, fail_rate * 100,
    )
    return "passed"


def _is_verification_advisory(state: ExamForgeState) -> bool:
    """상태 플래그나 env 설정으로 advisory 모드인지 확인한다."""
    return state.get("verification_advisory") is True or verification_advisory_enabled()
