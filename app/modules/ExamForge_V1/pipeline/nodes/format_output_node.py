"""최종 출력(HTML + JSON)을 생성하는 노드."""
from __future__ import annotations

import math
import time

from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.pipeline.nodes._html_builder import build_exam_html, build_answers_html
from app.modules.ExamForge_V1.pipeline.nodes.programming_context import has_code_snippets
from app.modules.ExamForge_V1.pipeline.nodes.programming_context import looks_like_programming_source
from app.modules.ExamForge_V1.quality.metrics import compute_quality_metrics
from app.modules.ExamForge_V1.quality.cjk_sanitizer import sanitize_exam_questions
from app.modules.ExamForge_V1.common.config import verification_advisory_enabled
from app.modules.ExamForge_V1.common.logger import get_logger
from app.modules.ExamForge_V1.common.verification_status import (
    advisory_filtered_failed_ids,
    verification_advisory_keys,
)

logger = get_logger(__name__)

# 최소 완료 비율 — 이 비율 미만이면 graceful degradation(needs_more_source)으로 분기한다
_MINIMUM_COMPLETION_RATIO = 0.5
_MINIMUM_COVERAGE_SCORE = 0.5
# 출고 floor 절대 하한 — 유효 목표가 아무리 작아도 이만큼은 확보돼야 정상 출고로 본다.
_OUTCOME_FLOOR_ABSOLUTE = 5


def _completion_floor(effective_target: int) -> int:
    """정상 출고로 인정하는 최소 고유 문항 수(floor)를 계산한다.

    floor = max(_OUTCOME_FLOOR_ABSOLUTE, ceil(effective_target * _MINIMUM_COMPLETION_RATIO)).
    단 effective_target 자체가 floor보다 작으면(아주 좁은 소스) effective_target을 floor로 쓴다.
    """
    if effective_target <= 0:
        return _OUTCOME_FLOOR_ABSOLUTE
    ratio_floor = math.ceil(effective_target * _MINIMUM_COMPLETION_RATIO)
    floor = max(_OUTCOME_FLOOR_ABSOLUTE, ratio_floor)
    return min(floor, effective_target)


async def format_output_node(state: ExamForgeState) -> dict:
    """시험지 HTML과 답안지 HTML을 생성한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환해 불필요한 처리를 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: format_output_node")
    plan = state.get("exam_plan", {})
    questions = sanitize_exam_questions(_apply_plan_points(state.get("calibrated_questions", []), plan))
    retry_count = state.get("retry_count", 0)
    timings = state.get("timings", {})
    start_time = timings.get("start", time.time())
    topic_weights = plan.get("topic_weights", {})
    generation_time = time.time() - start_time

    # 검증 데이터 없으면 실패로 간주 (품질 무력화 방지)
    verification_results = [q.get("_verification", {"passed": False}) for q in questions]

    # 품질 메트릭 계산
    try:
        quality_metrics = compute_quality_metrics(
            questions=questions,
            topic_weights=topic_weights,
            verification_results=verification_results,
            generation_time_sec=generation_time,
            retry_count=retry_count,
        )
    except Exception as exc:
        logger.warning("품질 메트릭 계산 실패 — 빈 메트릭 사용: %s", exc)
        quality_metrics = {}

    # HTML 생성 (추출된 빌더 사용)
    try:
        exam_html = build_exam_html(questions, plan)
        answers_html = build_answers_html(questions, plan)
    except Exception as exc:
        logger.warning("HTML 생성 실패 — 빈 HTML 사용: %s", exc)
        exam_html = ""
        answers_html = ""

    # HTML이 모두 빈 경우 유효한 시험지가 아님 — 실패로 강제
    if not exam_html and not answers_html:
        logger.error("시험지·답안지 HTML 모두 빈 상태 — 파이프라인 실패 처리")
        return {
            "calibrated_questions": [
                {k: v for k, v in q.items() if not k.startswith("_")} for q in questions
            ],
            "output_html": "",
            "answers_html": "",
            "quality_metrics": quality_metrics,
            "pipeline_status": "failed",
            "pipeline_outcome": "failed_html_generation",
            "error_message": "시험지·답안지 HTML 생성 모두 실패 — 배포 불가",
        }

    # 한쪽만 빈 경우 — 부분 생성으로 간주해 경고만 남긴다
    if not exam_html or not answers_html:
        missing = "시험지" if not exam_html else "답안지"
        logger.warning("%s HTML 빈 상태 — 부분 생성으로 계속 진행", missing)

    # _verification 필드 제거 (응답에 불필요)
    clean_questions = [
        {k: v for k, v in q.items() if not k.startswith("_")}
        for q in questions
    ]

    # ── 부분완료 출고 무결화: templateId/questionId 빈값 문항 사전 드롭 ──
    # codex가 목표보다 적게/중복 생성할 때 templateId·question_id가 비어 있는
    # 미완 문항이 섞이면 Spring 콜백이 VALIDATION_001(400)으로 거부된다.
    # 출고 직전에 무결하지 않은 문항을 드롭해 유효 문항만 Spring에 전달한다.
    # 드롭 후 seal은 하위 attach_answer_key_seal이 자동으로 유효 집합 기준으로 재계산한다.
    valid_questions, dropped_count = _drop_invalid_questions(clean_questions)
    if dropped_count > 0:
        logger.warning(
            "format_output_node: templateId/questionId 빈값 문항 %d개 드롭 (원본 %d → 유효 %d)",
            dropped_count,
            len(clean_questions),
            len(valid_questions),
        )
    clean_questions = valid_questions

    # retry가 소진되었고 실패 문항이 남아있을 때만 "exhausted" 표시
    # (failed_question_ids만 보면 retry_router 10% 허용 케이스가 오분류됨)
    failed_ids = _active_failed_ids(state)
    max_retries = state.get("max_retries", 3)
    pipeline_outcome = (
        "exhausted" if (retry_count >= max_retries and failed_ids) else "passed"
    )

    # 완료 비율 검사 — outcome과 무관하게 항상 검사해 "축소된 시험" 문제를 감지한다.
    # exam_config.total_questions는 plan_exam_node에서 소스 폭 캡이 적용된 유효 목표다.
    # 사용자에게 보여줄 원래 요청 수는 requested_question_count로 별도 보존돼 있다.
    exam_config = state.get("exam_config", {})
    effective_target = exam_config.get("total_questions", 0)
    requested_count = exam_config.get("requested_question_count", effective_target)
    # 드롭 이후의 유효(고유) 문항 수를 기준으로 비율을 계산한다
    actual_count = len(clean_questions)
    error_message = state.get("error_message")

    # 유효 문항이 0개면 FAILED 콜백을 보내야 하므로 즉시 실패 처리한다(진짜 실패).
    if actual_count == 0:
        logger.error(
            "format_output_node: 드롭 후 유효 문항 0개 — 파이프라인 실패 처리"
        )
        return {
            "calibrated_questions": [],
            "output_html": exam_html,
            "answers_html": answers_html,
            "quality_metrics": quality_metrics,
            "pipeline_status": "failed",
            "pipeline_outcome": "failed_no_valid_questions",
            "error_message": "식별자 무결한 문항이 없음 — Spring 콜백 전송 불가",
        }

    # 유효 목표 기반 출고 floor — 좁은 소스로 고유 문항이 부족한 경우(0 < unique < floor)
    # 진짜 FAILED 대신 needs_more_source(비-FAILED)로 분기해 확보된 고유 문항을 출고하고
    # 사용자에게 "자료 부족(요청 N / 생성 M)" 안내를 보낸다.
    floor = _completion_floor(int(effective_target or 0))
    if effective_target > 0 and actual_count < effective_target:
        completion_ratio = actual_count / effective_target
        if actual_count < floor:
            # graceful degradation — 출고는 하되 자료 부족을 명시한다(비-FAILED).
            pipeline_outcome = "needs_more_source"
            error_message = (
                f"자료 부족: 요청 {requested_count}문항 중 고유 {actual_count}문항만 "
                f"생성 가능(유효 목표 {effective_target}, 출고 floor {floor}). "
                "자료(슬라이드/챕터)를 보강하면 더 많은 문항을 생성할 수 있습니다."
            )
            logger.warning(
                "출고 floor 미달(needs_more_source): 고유 %d개 < floor %d "
                "(유효 목표 %d, 요청 %s)",
                actual_count, floor, effective_target, requested_count,
            )
        elif completion_ratio < 1.0 and pipeline_outcome == "passed":
            # 일부 문항 누락이지만 floor 이상 — 부분 완료로 출고한다
            pipeline_outcome = "passed_partial"
            logger.info(
                "부분 완료: %d/%d (%.1f%%) — passed_partial로 표시",
                actual_count, effective_target, completion_ratio * 100,
            )
    if pipeline_outcome == "passed" and _is_low_coverage(quality_metrics, topic_weights):
        pipeline_outcome = "failed_quality_gate"
        error_message = (
            f"주제 커버리지 미달: coverage_score={quality_metrics.get('coverage_score', 0.0)}. "
            "계획된 주제 분포에 맞게 문항을 다시 생성해야 합니다."
        )
    if pipeline_outcome == "passed" and _missing_programming_code(state, clean_questions):
        pipeline_outcome = "failed_quality_gate"
        error_message = "프로그래밍 과목인데 코드 예제 문항이 없어 배포 품질 기준에 미달합니다."

    # 품질 게이트(커버리지/코드부재)는 1차적으로 "재시도해서 더 나은 문항을 만들라"는 신호다.
    # 따라서 재시도 여유가 있으면 failed_quality_gate를 유지해 route_after_validation이
    # 재생성하도록 둔다. 단 재시도가 소진된 터미널 케이스에서는, floor 이상 유효 문항이
    # 확보돼 있으면 전체를 0으로 차단(FAILED)하지 말고 확보된 시험을 passed_partial로 출고한다
    # (사용자에게 빈 결과보다 부분 시험이 낫다. 예: 스프링부트 개념 문항은 코드 스니펫이 적어
    #  _missing_programming_code에 걸리지만 18/20을 0으로 버리는 건 과도하다).
    # degrade 임계는 상대 floor가 아니라 "실질적 시험" 절대 하한(_OUTCOME_FLOOR_ABSOLUTE)으로 둔다.
    # → 1~2문항짜리 빈약한 시험은 품질게이트로 막되(예: 코드 1문항 Rust 시험),
    #   18/20처럼 충분한 시험은 코드/커버리지 경고가 있어도 출고한다.
    retries_exhausted = retry_count >= max_retries
    if (
        pipeline_outcome == "failed_quality_gate"
        and retries_exhausted
        and actual_count >= _OUTCOME_FLOOR_ABSOLUTE
    ):
        logger.warning(
            "품질 게이트 미달이나 재시도 소진+유효 문항 %d개(≥%d) — "
            "FAILED 차단 대신 passed_partial로 출고 (%s)",
            actual_count, _OUTCOME_FLOOR_ABSOLUTE, error_message,
        )
        pipeline_outcome = "passed_partial"

    # "failed*"/"exhausted" → "failed", "passed_partial"/"needs_more_source" → "partial",
    # 그 외 → "complete". needs_more_source는 비-FAILED(부분 출고)이므로 partial로 둔다.
    if pipeline_outcome.startswith("failed") or pipeline_outcome == "exhausted":
        final_status = "failed"
    elif pipeline_outcome in ("passed_partial", "needs_more_source"):
        final_status = "partial"
    else:
        final_status = "complete"

    logger.info(
        "노드 완료: format_output_node (%.2fs) outcome=%s status=%s",
        time.time() - node_start,
        pipeline_outcome,
        final_status,
    )
    return {
        "calibrated_questions": clean_questions,
        "output_html": exam_html,
        "answers_html": answers_html,
        "quality_metrics": quality_metrics,
        "pipeline_status": final_status,
        "pipeline_outcome": pipeline_outcome,
        "error_message": error_message,
    }


def _apply_plan_points(questions: list[dict], plan: dict) -> list[dict]:
    """시험 계획의 템플릿별 배점을 실제 문항에 반영한다."""
    point_map = {
        alloc.get("template_id", ""): alloc.get("points_per_question", 1.0)
        for alloc in plan.get("type_allocations", [])
    }
    if not point_map:
        return questions
    adjusted: list[dict] = []
    for q in questions:
        q_copy = q.copy()
        template_id = q_copy.get("template_id", "")
        q_copy["points"] = float(
            point_map.get(template_id, q_copy.get("points", 1.0))
        )
        adjusted.append(q_copy)
    return adjusted


def _is_low_coverage(metrics: dict, topic_weights: dict[str, float]) -> bool:
    """여러 주제를 요구한 시험에서 커버리지가 낮은지 확인한다. 누락 시 0.0 처리."""
    if len(topic_weights) <= 1:
        return False
    return metrics.get("coverage_score", 0.0) < _MINIMUM_COVERAGE_SCORE


def _missing_programming_code(state: ExamForgeState, questions: list[dict]) -> bool:
    """코드 과목인데 코드 예제 문항이 없는 최종 산출물을 차단한다."""
    source_text = state.get("source_text", "")
    return looks_like_programming_source(source_text) and not has_code_snippets(questions)


def _active_failed_ids(state: ExamForgeState) -> list[str]:
    """최신 검증 리포트 기준의 실패 문항만 반환한다."""
    questions = state.get("calibrated_questions", [])
    verification_advisory = _is_verification_advisory(state)
    results = state.get("validation_report", {}).get("results")
    if not isinstance(results, list):
        return advisory_filtered_failed_ids(
            state.get("failed_question_ids", []),
            questions,
            verification_advisory=verification_advisory,
        )
    failed_ids = [
        r.get("question_id", "")
        for r in results
        if isinstance(r, dict) and not r.get("passed", False) and not r.get("parse_failed", False)
    ]
    if not verification_advisory:
        return failed_ids
    advisory_keys = verification_advisory_keys(questions)
    filtered = [item for item in failed_ids if str(item) not in advisory_keys]
    if len(filtered) != len(failed_ids):
        logger.warning("format_output_node: 검증 advisory 모드 — 최종 실패 ID에서 검증기 판단 제외")
    return filtered


def _is_verification_advisory(state: ExamForgeState) -> bool:
    """상태 플래그나 env 설정으로 advisory 모드인지 확인한다."""
    return state.get("verification_advisory") is True or verification_advisory_enabled()


def _drop_invalid_questions(
    questions: list[dict],
) -> tuple[list[dict], int]:
    """templateId 또는 question_id가 빈값(공백 포함)인 문항을 드롭하고 유효 목록을 반환한다.

    Spring 콜백은 두 식별자 중 하나라도 비어 있으면 VALIDATION_001(400)으로 거부한다.
    codex가 목표보다 적게 생성하거나 중복 드롭 후 슬롯이 비어 있을 때
    미완 placeholder 문항이 섞이는 것을 이 지점에서 차단한다.

    Returns:
        (유효_문항_리스트, 드롭_개수)
    """
    valid: list[dict] = []
    dropped = 0
    for q in questions:
        template_id = str(q.get("template_id") or "").strip()
        question_id = str(q.get("question_id") or "").strip()
        if not template_id or not question_id:
            dropped += 1
            continue
        valid.append(q)
    return valid, dropped
