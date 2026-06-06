"""검증 결과에 따라 재시도/통과를 라우팅하는 노드."""
from __future__ import annotations

import time

from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.common.ai_bridge import get_current_budget
from app.modules.ExamForge_V1.common.config import missing_retry_cap, verification_advisory_enabled
from app.modules.ExamForge_V1.common.logger import get_logger
from app.modules.ExamForge_V1.common.verification_status import (
    advisory_filtered_failed_ids,
    has_distractor_validity_hard_fail,
    has_parse_failed_majority,
    verification_counts,
)

logger = get_logger(__name__)


# 개수 부족 재시도가 진전 없이 반복되는 것을 허용하는 최대 라운드 수.
# 이 횟수만큼 missing_count가 줄지 않으면(dedup 비수렴) 유니크 문항만 출고한다.
_COUNT_STUCK_ROUND_CAP = 2


def _is_missing_retry_cap_reached(state: ExamForgeState) -> bool:
    """개수 부족 전용 재시도가 env 캡에 도달했는지 판단한다.

    missing_retry_count >= missing_retry_cap() 이면 True.
    codex 속도(~5분/회)를 고려해 기본 캡은 1회로, 캡 도달 시
    유효 문항만으로 passed 출고해 타임아웃을 방지한다.
    """
    cap = missing_retry_cap()
    current = state.get("missing_retry_count", 0)
    return isinstance(current, int) and current >= cap


async def retry_router_node(state: ExamForgeState) -> dict:
    """실제 재시도가 필요한 경우에만 카운터를 증가시킨다.

    passed/exhausted 경로에서는 카운터를 변경하지 않아
    off-by-one 보고 오류를 방지한다.

    개수 부족 비수렴 추적: missing_count가 직전 라운드 대비 줄지 않으면
    count_stuck_rounds를 증가시키고, 줄면 0으로 리셋한다. 이 값을
    route_after_validation의 비수렴 캡이 참조한다.

    missing_retry_count: missing_count > 0 이 원인인 retry 전용 카운터.
    env EXAMFORGE_MISSING_RETRY_CAP(기본 1) 초과 시 추가 재시도 없이 passed 출고.
    """
    # 상위 노드에서 에러가 전파된 경우 즉시 반환
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: retry_router_node")

    # 개수 부족 진전 추적 — route 결정 전에 stuck 카운터를 갱신한다.
    stuck_update = _track_count_progress(state)

    # 내부 route 판단은 갱신된 stuck 값을 반영해야 한다(엣지 호출과 일관성).
    # langgraph는 이 노드가 state를 갱신한 뒤 route_after_validation을 엣지로
    # 다시 호출하므로, 내부 호출도 동일한 갱신본을 보게 해 retry 카운터 증분이
    # 엣지 라우팅과 어긋나지 않게 한다.
    route_state = {**state, **stuck_update}
    route = route_after_validation(route_state)
    if route == "retry":
        # missing_count > 0 이 원인인지 확인해 전용 카운터 증가
        report = state.get("validation_report", {})
        missing_count = report.get("missing_count")
        missing_retry_update: dict = {}
        if isinstance(missing_count, int) and missing_count > 0:
            missing_retry_update = {
                "missing_retry_count": state.get("missing_retry_count", 0) + 1
            }
        # 실제 재시도 시에만 retry_count 카운터 증가
        logger.info("노드 완료: retry_router_node (%.2fs) → retry", time.time() - node_start)
        return {
            "retry_count": state.get("retry_count", 0) + 1,
            **stuck_update,
            **missing_retry_update,
        }
    # 통과 또는 소진 시 카운터 유지
    logger.info("노드 완료: retry_router_node (%.2fs) → %s", time.time() - node_start, route)
    return stuck_update


def _track_count_progress(state: ExamForgeState) -> dict:
    """개수 부족 재시도의 진전 여부를 추적해 count_stuck_rounds를 갱신한다.

    missing_count가 직전보다 줄면 stuck=0(진전), 같거나 늘면 stuck+1(비수렴).
    missing_count가 0이거나 없으면 추적을 리셋한다.
    """
    report = state.get("validation_report", {})
    missing_count = report.get("missing_count")
    if not isinstance(missing_count, int) or missing_count <= 0:
        return {"count_stuck_rounds": 0, "prev_missing_count": 0}

    prev = state.get("prev_missing_count", -1)
    stuck = state.get("count_stuck_rounds", 0)
    if prev >= 0 and missing_count >= prev:
        # 진전 없음(같거나 악화) — 비수렴 카운터 증가
        stuck += 1
    else:
        # 진전 있음(미달 감소) 또는 첫 관측 — 카운터 리셋
        stuck = 0
    return {"count_stuck_rounds": stuck, "prev_missing_count": missing_count}


def _count_retry_non_converging(state: ExamForgeState, missing_count: int) -> bool:
    """개수 부족 재시도가 비수렴 상한에 도달했는지 판단한다.

    count_stuck_rounds가 캡 이상이면 True — 더 재시도해도 dedup이 같은 중복을
    드롭해 수렴 못 하므로 유니크 문항만 출고한다.
    """
    stuck = state.get("count_stuck_rounds", 0)
    return isinstance(stuck, int) and stuck >= _COUNT_STUCK_ROUND_CAP


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
        # missing_retry_cap 우선 체크: env EXAMFORGE_MISSING_RETRY_CAP(기본 1) 도달 시
        # 추가 재시도 없이 확보된 유효 문항으로 passed 출고한다.
        # codex는 1회 ~5분 소요 — 캡 초과 재시도가 타임아웃의 근본 원인이므로 최우선 차단.
        if _is_missing_retry_cap_reached(state):
            logger.warning(
                "route_after_validation: missing_retry_cap(%d) 도달(missing_count=%d) — "
                "유효 문항만으로 passed 출고(타임아웃 방지)",
                missing_retry_cap(),
                missing_count,
            )
            return "passed"
        # 비수렴 캡: dedup이 매번 같은 중복을 드롭해 missing_count가 줄지 않으면
        # 무한 재시도로 예산을 태운다. 개수 부족 재시도가 진전 없이 상한에 도달하면
        # 확보된 유니크 문항만 출고하도록 passed로 빠진다(total_questions 동기화는
        # format_output/response에서 처리). 진전(미달 감소)이 있으면 정상 재시도.
        if _count_retry_non_converging(state, missing_count):
            logger.warning(
                "route_after_validation: 개수 부족 재시도 비수렴(missing_count=%d) — "
                "유니크 문항만 출고(passed)로 종료",
                missing_count,
            )
            return "passed"
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

    # --- 오답 타당성(기준7) hard-fail 게이트 ---
    # 동치/참 오답은 콘텐츠 정확성 결함이라 advisory 모드여도, 실패율이 낮아도
    # 무조건 repair로 보내야 한다. 단 1건이라도 있으면 retry로 라우팅한다(예산
    # 소진/최대 재시도 시에는 위쪽 가드가 이미 exhausted로 빼낸다).
    if has_distractor_validity_hard_fail(questions):
        _dest = "exhausted" if retry_count >= max_retries else "retry"
        logger.warning(
            "route_after_validation: 오답 타당성 hard-fail 감지(advisory 무시) — %s", _dest,
        )
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
