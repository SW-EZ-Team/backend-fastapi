"""ExamForge 제출 답안 채점 테스트."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.ExamForge_V1.grading.exceptions import RubricGradingError
from app.modules.ExamForge_V1.grading.engine import grade_submission
from app.modules.ExamForge_V1.grading.seal import create_answer_key_seal
from app.modules.ExamForge_V1.schemas.grading import (
    GradeSubmissionRequest,
    GradingMode,
    SubmittedAnswer,
)
from app.modules.ExamForge_V1.tests.grading_samples import (
    BooleanScoreConnector,
    InconsistentConnector,
    RecordingConnector,
    blank_question,
    choice_question,
    essay_question,
    matching_question,
    ordering_question,
    practical_question,
)


@pytest.mark.asyncio
async def test_grade_submission_scores_structured_question_types() -> None:
    """객관식, 빈칸, 순서, 연결형을 실제 채점 규칙으로 합산한다."""
    questions = [
        choice_question(),
        blank_question(),
        ordering_question(),
        matching_question(),
    ]
    request = GradeSubmissionRequest(
        attempt_id="attempt-1",
        exam_id="exam-1",
        answer_key_seal=create_answer_key_seal("exam-1", questions),
        questions=questions,
        submitted_answers=[
            SubmittedAnswer(question_id="q-choice", answer={"selected": "2"}),
            SubmittedAnswer(question_id="q-blank", answer={"blanks": ["애자일", "폭포수"]}),
            SubmittedAnswer(question_id="q-order", answer=["요구사항", "설계", "구현"]),
            SubmittedAnswer(
                question_id="q-match",
                answer={"Singleton": "생성 패턴", "Adapter": "구조 패턴"},
            ),
        ],
    )

    response = await grade_submission(request)

    assert response.total_score == pytest.approx(8.0)
    assert response.max_score == pytest.approx(9.0)
    assert response.percentage == pytest.approx(88.89)
    assert response.passed is True
    assert [item.score for item in response.results] == [2.0, 1.0, 3.0, 2.0]


@pytest.mark.asyncio
async def test_ai_rubric_grading_uses_connector_contract() -> None:
    """서술형은 텍스트 커넥터를 호출하고 JSON 채점 결과를 그대로 구조화한다."""
    connector = RecordingConnector()
    question = essay_question()
    questions = [question]
    request = GradeSubmissionRequest(
        attempt_id="attempt-rubric",
        exam_id="exam-rubric",
        answer_key_seal=create_answer_key_seal("exam-rubric", questions),
        questions=questions,
        submitted_answers=[
            SubmittedAnswer(
                question_id="q-essay",
                answer="애자일은 변화에 대응하지만 근거 설명은 짧습니다.",
            )
        ],
    )

    response = await grade_submission(request, connector=connector)

    assert len(connector.requests) == 1
    assert "애자일은 변화에 대응" in connector.requests[0].user
    result = response.results[0]
    assert result.grading_mode == GradingMode.AI_RUBRIC
    assert result.score == pytest.approx(3.5)
    assert result.confidence == pytest.approx(0.82)
    assert result.needs_manual_review is False
    assert len(result.rubric_breakdown) == 2


@pytest.mark.asyncio
async def test_rubric_exact_answer_skips_ai_call() -> None:
    """실기형이 명시 허용 답안과 일치하면 비용이 드는 AI 호출을 하지 않는다."""
    connector = RecordingConnector()
    question = practical_question()
    questions = [question]
    request = GradeSubmissionRequest(
        attempt_id="attempt-practical",
        exam_id="exam-practical",
        answer_key_seal=create_answer_key_seal("exam-practical", questions),
        questions=questions,
        submitted_answers=[SubmittedAnswer(question_id="q-practical", answer="INNER JOIN")],
    )

    response = await grade_submission(request, connector=connector)

    assert len(connector.requests) == 0
    assert response.total_score == pytest.approx(4.0)
    assert response.results[0].grading_mode == GradingMode.DETERMINISTIC


@pytest.mark.asyncio
async def test_ai_rubric_rejects_inconsistent_breakdown() -> None:
    """AI 루브릭 총점과 세부 점수 합계가 다르면 실패한다."""
    question = essay_question()
    questions = [question]
    request = GradeSubmissionRequest(
        attempt_id="attempt-inconsistent",
        exam_id="exam-inconsistent",
        answer_key_seal=create_answer_key_seal("exam-inconsistent", questions),
        questions=questions,
        submitted_answers=[
            SubmittedAnswer(question_id="q-essay", answer="근거가 부족한 답안입니다.")
        ],
    )

    with pytest.raises(RubricGradingError):
        await grade_submission(request, connector=InconsistentConnector())


@pytest.mark.asyncio
async def test_ai_rubric_rejects_boolean_score() -> None:
    """AI가 boolean을 숫자 필드로 보내면 채점 결과로 채택하지 않는다."""
    question = essay_question()
    questions = [question]
    request = GradeSubmissionRequest(
        attempt_id="attempt-bool",
        exam_id="exam-bool",
        answer_key_seal=create_answer_key_seal("exam-bool", questions),
        questions=questions,
        submitted_answers=[SubmittedAnswer(question_id="q-essay", answer="답안")],
    )

    with pytest.raises(RubricGradingError):
        await grade_submission(request, connector=BooleanScoreConnector())


def test_grade_submission_rejects_unknown_answer_id() -> None:
    """문제 목록에 없는 question_id 답안은 요청 검증 단계에서 거부한다."""
    questions = [choice_question()]
    with pytest.raises(ValidationError):
        GradeSubmissionRequest(
            attempt_id="attempt-invalid",
            exam_id="exam-invalid",
            answer_key_seal=create_answer_key_seal("exam-invalid", questions),
            questions=questions,
            submitted_answers=[SubmittedAnswer(question_id="q-missing", answer="1")],
        )


def test_grade_submission_rejects_duplicate_answer_id() -> None:
    """같은 문항 답안을 두 번 보내면 요청 검증 단계에서 거부한다."""
    questions = [choice_question()]
    with pytest.raises(ValidationError):
        GradeSubmissionRequest(
            attempt_id="attempt-duplicate",
            exam_id="exam-duplicate",
            answer_key_seal=create_answer_key_seal("exam-duplicate", questions),
            questions=questions,
            submitted_answers=[
                SubmittedAnswer(question_id="q-choice", answer="1"),
                SubmittedAnswer(question_id="q-choice", answer="2"),
            ],
        )
