"""제출물 단위 채점 오케스트레이터."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.modules.ExamForge_V1.common.ai_bridge import AIConnector
from app.modules.ExamForge_V1.common.config import seal_enforce_mode
from app.modules.ExamForge_V1.grading.deterministic import (
    grade_exact_question,
    grade_objective_question,
    grade_unanswered_question,
)
from app.modules.ExamForge_V1.grading.exceptions import AnswerKeyIntegrityError
from app.modules.ExamForge_V1.grading.rubric import RUBRIC_TEMPLATES, grade_rubric_question
from app.modules.ExamForge_V1.grading.seal import create_answer_key_seal, verify_answer_key_seal
from app.modules.ExamForge_V1.schemas.grading import (
    GradeQuestion,
    GradeSubmissionRequest,
    GradeSubmissionResponse,
    GradingStatus,
    JsonValue,
    QuestionGradeResult,
)

_LOG = logging.getLogger(__name__)


async def grade_submission(
    request: GradeSubmissionRequest,
    connector: AIConnector | None = None,
) -> GradeSubmissionResponse:
    """제출물 전체를 실제 채점 규칙으로 채점한다."""
    _verify_answer_key(request)
    answer_map = {answer.question_id: answer.answer for answer in request.submitted_answers}
    results: list[QuestionGradeResult] = []
    for question in request.questions:
        if question.question_id not in answer_map:
            results.append(grade_unanswered_question(question))
            continue
        results.append(await _grade_question(question, answer_map[question.question_id], connector))
    return _build_response(request, results)


def _verify_answer_key(request: GradeSubmissionRequest) -> None:
    """정답/배점/루브릭 근거가 생성 시점 그대로인지 검증한다.

    advisory 모드(EXAMFORGE_SEAL_ENFORCE=false, 기본값):
        HMAC 불일치 시 WARNING 로그(computed·received 접두 6자, 시크릿 미노출)를 남기고
        채점을 계속 진행한다.
        이유: 크로스서비스 canonical 재현이 반복 실패(Spring mapper null→emptyList 치환 등)해
        403→502 채점 차단이 발생한다. 내부 X-API-Key 인증 경로라 외부 변조 위험은 낮다.
        신호는 보존(WARNING 로그)하되 사용자 채점을 막지 않는다.

    강제 모드(EXAMFORGE_SEAL_ENFORCE=true):
        기존처럼 HMAC 불일치 시 AnswerKeyIntegrityError(→403)를 발생시킨다.
        canonical 정합이 확인된 뒤 재강제 시 사용한다.
    """
    verified = verify_answer_key_seal(
        request.exam_id,
        request.questions,
        request.answer_key_seal,
    )
    if verified:
        return

    if seal_enforce_mode():
        # 강제 모드: 기존 동작 유지 — 403 반환
        raise AnswerKeyIntegrityError("정답 키 서명 검증 실패")

    # advisory 모드: WARNING 로그만 남기고 채점 계속 진행
    # computed seal 접두 6자만 노출해 디버그 단서를 주되 시크릿 전체는 절대 출력하지 않는다.
    computed = create_answer_key_seal(request.exam_id, request.questions)
    received = request.answer_key_seal or ""
    _LOG.warning(
        "seal advisory: HMAC 불일치 — computed 접두='%s...' received 접두='%s...' "
        "exam_id=%s question_count=%d — 채점 계속 진행(EXAMFORGE_SEAL_ENFORCE=false)",
        computed[:6] if len(computed) > 6 else computed,
        received[:6] if len(received) > 6 else received,
        request.exam_id,
        len(request.questions),
    )


async def _grade_question(
    question: GradeQuestion,
    answer: JsonValue,
    connector: AIConnector | None,
) -> QuestionGradeResult:
    """문항 유형에 맞는 채점기를 호출한다."""
    if question.template_id not in RUBRIC_TEMPLATES:
        return grade_objective_question(question, answer)
    exact = grade_exact_question(question, answer)
    if exact.is_correct:
        return exact
    return await grade_rubric_question(question, answer, connector)


def _build_response(
    request: GradeSubmissionRequest,
    results: list[QuestionGradeResult],
) -> GradeSubmissionResponse:
    """문항 결과를 제출물 전체 점수로 합산한다."""
    total_score = round(sum(item.score for item in results), 4)
    max_score = round(sum(item.max_score for item in results), 4)
    percentage = round((total_score / max_score) * 100, 2)
    manual = any(item.needs_manual_review for item in results)
    status = GradingStatus.MANUAL_REVIEW_REQUIRED if manual else GradingStatus.GRADED
    return GradeSubmissionResponse(
        attempt_id=request.attempt_id,
        exam_id=request.exam_id,
        total_score=total_score,
        max_score=max_score,
        percentage=percentage,
        passed=percentage >= request.pass_percentage and not manual,
        grading_status=status,
        graded_at=datetime.now(timezone.utc),
        results=results,
    )
