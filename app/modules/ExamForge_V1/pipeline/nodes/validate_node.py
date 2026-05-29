"""3계층 검증 노드: 구조 + 교차문제 + 전체."""
from __future__ import annotations

import time

from pydantic import ValidationError as PydanticValidationError

from app.modules.ExamForge_V1.common.errors import ExamForgeError
from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.templates.registry import get_template
from app.modules.ExamForge_V1.quality.deduplicator import check_duplicates
from app.modules.ExamForge_V1.quality.consistency_checker import check_consistency
from app.modules.ExamForge_V1.quality.coverage_analyzer import analyze_coverage
from app.modules.ExamForge_V1.common.logger import get_logger
from app.modules.ExamForge_V1.pipeline.nodes.programming_context import has_code_snippets
from app.modules.ExamForge_V1.pipeline.nodes.programming_context import looks_like_programming_source

logger = get_logger(__name__)


async def validate_node(state: ExamForgeState) -> dict:
    """3계층 검증을 오케스트레이션한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환해 불필요한 검증 비용을 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: validate_node")
    questions = state.get("verified_questions", [])

    # 상위 노드에서 데이터가 비었으면 즉시 반환 — 결정적 실패에 대한 무의미한 재시도 방지
    if not questions:
        logger.warning("validate_node: 검증할 문제 없음 — 즉시 종료")
        return {
            "validation_report": {},
            "failed_question_ids": [],
            "pipeline_status": "error",
            "error_message": "이전 단계에서 검증 가능한 문제가 생성되지 않음",
        }

    plan = state.get("exam_plan", {})
    topic_weights = plan.get("topic_weights", {})

    # 1계층: 개별 구조 검증
    results, failed_ids = _validate_structure(questions)

    # 2계층: 교차 문제 검증
    global_issues, cross_failed, dedup_score = _validate_cross_question(questions)
    for did in cross_failed:
        if did not in failed_ids:
            failed_ids.append(did)

    # 3계층: 전체 수준 검증
    coverage_score, uncovered = _validate_global(questions, topic_weights)
    if uncovered:
        global_issues.append(f"미커버 주제: {', '.join(uncovered[:5])}")
    _apply_programming_code_gate(state, questions, failed_ids, global_issues)

    # 정답 정확률 계산
    accuracy_rate = _compute_accuracy_rate(questions)

    # AKAR: 정확률 0.95 미만이면 미통과 문제를 재시도 목록에 추가
    if accuracy_rate < 0.95:
        for q in questions:
            verification = q.get("_verification")
            if verification is None or not verification.get("passed", False):
                draft_id = q.get("draft_id", q.get("question_id", ""))
                if draft_id and draft_id not in failed_ids:
                    failed_ids.append(draft_id)

    report = {
        "results": results,
        "global_issues": global_issues,
        "coverage_score": coverage_score,
        "dedup_score": dedup_score,
        "answer_accuracy_rate": accuracy_rate,
    }

    logger.info("노드 완료: validate_node (%.2fs)", time.time() - node_start)
    return {
        "validation_report": report,
        "failed_question_ids": failed_ids,
        "pipeline_status": "routing",
    }


def _validate_structure(
    questions: list[dict],
) -> tuple[list[dict], list[str]]:
    """개별 문제의 구조를 검증한다."""
    results: list[dict] = []
    failed_ids: list[str] = []

    for q in questions:
        template_id = q.get("template_id", "")
        q_id = q.get("question_id", q.get("draft_id", ""))
        # 재시도 필터링은 draft_id 기준으로 수행하므로 draft_id를 실패 목록에 저장
        draft_id = q.get("draft_id", q_id)
        issues = _check_single_structure(q, template_id)

        # 교차 모델 검증 결과 포함
        verification = q.get("_verification", {})
        if not verification.get("passed", False):
            issues.extend(verification.get("issues", []))

        passed = len(issues) == 0
        if not passed:
            failed_ids.append(draft_id)

        results.append({
            "question_id": q_id,
            "passed": passed,
            "issues": issues,
        })

    return results, failed_ids


def _check_single_structure(q: dict, template_id: str) -> list[str]:
    """단일 문제의 구조 유효성을 확인한다."""
    if not q.get("stem", "").strip():
        return ["문제 줄기(stem)가 비어 있음"]
    try:
        template = get_template(template_id)
        from app.modules.ExamForge_V1.schemas.question import Question
        question_obj = Question(**q)
        return template.validate_structure(question_obj)
    except (ExamForgeError, PydanticValidationError, ValueError, TypeError) as e:
        return [f"구조 검증 오류: {str(e)[:100]}"]


def _validate_cross_question(
    questions: list[dict],
) -> tuple[list[str], list[str], float]:
    """교차 문제 검증 (중복, 일관성)을 수행하고 dedup_score를 함께 반환한다."""
    global_issues: list[str] = []
    failed_ids: list[str] = []

    try:
        dedup_score, dup_pairs = check_duplicates(questions)
    except Exception as exc:
        logger.warning("중복 검사 실패 — 건너뜀: %s", exc)
        dedup_score, dup_pairs = 0.0, []
    if dup_pairs:
        global_issues.append(f"중복 의심 쌍 {len(dup_pairs)}건 발견")

    try:
        inconsistencies = check_consistency(questions)
    except Exception as exc:
        logger.warning("일관성 검사 실패 — 건너뜀: %s", exc)
        inconsistencies = []
    if inconsistencies:
        global_issues.append(f"정답-보기 불일치 {len(inconsistencies)}건")
        # question_id → 문제 매핑을 미리 생성해 반복 탐색 방지
        q_map = {q.get("question_id", ""): q for q in questions}
        for inc in inconsistencies:
            inc_qid = inc.get("question_id", "")
            matched_q = q_map.get(inc_qid, {})
            # draft_id 기준으로 실패 목록 관리 (generate_questions_node와 일치)
            failed_ids.append(matched_q.get("draft_id", inc_qid))

    return global_issues, failed_ids, dedup_score


def _validate_global(
    questions: list[dict], topic_weights: dict[str, float],
) -> tuple[float, list[str]]:
    """전체 수준 검증 (커버리지)을 수행한다."""
    try:
        return analyze_coverage(questions, topic_weights)
    except Exception as exc:
        logger.warning("커버리지 분석 실패 — 폴백 사용: %s", exc)
        return 0.0, []


def _compute_accuracy_rate(questions: list[dict]) -> float:
    """교차 검증 통과율을 계산한다."""
    if not questions:
        return 0.0
    verified_count = sum(
        1 for q in questions
        if q.get("_verification", {}).get("passed", False)
    )
    return verified_count / len(questions)


def _apply_programming_code_gate(
    state: ExamForgeState,
    questions: list[dict],
    failed_ids: list[str],
    global_issues: list[str],
) -> None:
    """프로그래밍 과목에서 코드 예시 문항 누락을 재시도 대상으로 표시한다."""
    source_text = state.get("source_text", "")
    if not looks_like_programming_source(source_text) or has_code_snippets(questions):
        return
    global_issues.append("프로그래밍 과목인데 code_snippet 문항이 없음")
    for q in questions:
        draft_id = q.get("draft_id", q.get("question_id", ""))
        if draft_id and draft_id not in failed_ids:
            failed_ids.append(draft_id)
