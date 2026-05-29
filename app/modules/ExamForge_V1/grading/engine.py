"""제출물 단위 채점 오케스트레이터."""
from __future__ import annotations

from datetime import datetime, timezone

from app.modules.ExamForge_V1.common.ai_bridge import AIConnector
from app.modules.ExamForge_V1.grading.deterministic import (
    grade_exact_question,
    grade_objective_question,
    grade_unanswered_question,
)
from app.modules.ExamForge_V1.grading.exceptions import AnswerKeyIntegrityError
from app.modules.ExamForge_V1.grading.rubric import RUBRIC_TEMPLATES, grade_rubric_question
from app.modules.ExamForge_V1.grading.seal import verify_answer_key_seal
from app.modules.ExamForge_V1.schemas.grading import (
    GradeSubmissionRequest,
    GradeSubmissionResponse,
    GradingStatus,
    JsonValue,
    QuestionGradeResult,
)
from app.modules.ExamForge_V1.schemas.question import Question


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
    """정답/배점/루브릭 근거가 생성 시점 그대로인지 검증한다."""
    verified = verify_answer_key_seal(
        request.exam_id,
        request.questions,
        request.answer_key_seal,
    )
    if not verified:
        raise AnswerKeyIntegrityError("정답 키 서명 검증 실패")


async def _grade_question(
    question: Question,
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
