"""최종 출력(HTML + JSON)을 생성하는 노드."""
from __future__ import annotations

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

# 최소 완료 비율 — 이 비율 미만이면 유효한 시험으로 반환하지 않는다
_MINIMUM_COMPLETION_RATIO = 0.5
_MINIMUM_COVERAGE_SCORE = 0.5


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

    # 완료 비율 검사 — outcome과 무관하게 항상 검사해 "축소된 시험" 문제를 감지한다
    requested_count = state.get("exam_config", {}).get("total_questions", 0)
    # 드롭 이후의 유효 문항 수를 기준으로 비율을 계산한다
    actual_count = len(clean_questions)
    error_message = state.get("error_message")

    # 유효 문항이 0개면 FAILED 콜백을 보내야 하므로 즉시 실패 처리한다
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

    if requested_count > 0 and actual_count < requested_count:
        completion_ratio = actual_count / requested_count
        if completion_ratio < _MINIMUM_COMPLETION_RATIO:
            pipeline_outcome = "failed_minimum_threshold"
            error_message = (
                f"문제 생성 품질 미달: 요청 {requested_count}문항 중 "
                f"{actual_count}문항만 통과 ({actual_count}/{requested_count}). "
                "소스 자료를 보강하거나 난이도를 조정하세요."
            )
            logger.warning(
                "최소 완료 비율 미달: %d/%d (%.1f%% < %.1f%%)",
                actual_count, requested_count,
                completion_ratio * 100, _MINIMUM_COMPLETION_RATIO * 100,
            )
        elif completion_ratio < 1.0 and pipeline_outcome == "passed":
            # 일부 문항 누락이지만 최소 비율 이상 — 경고만 남기고 계속 진행
            pipeline_outcome = "passed_partial"
            logger.info(
                "부분 완료: %d/%d (%.1f%%) — passed_partial로 표시",
                actual_count, requested_count, completion_ratio * 100,
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

    # "failed*"/"exhausted" → "failed", "passed_partial" → "partial", 그 외 → "complete"
    if pipeline_outcome.startswith("failed") or pipeline_outcome == "exhausted":
        final_status = "failed"
    elif pipeline_outcome == "passed_partial":
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
