"""제출 답안 채점 API 스키마."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, JsonValue, field_validator, model_validator

from app.modules.ExamForge_V1.schemas.question import Question


class GradingMode(str, Enum):
    """문항별 채점 방식."""

    DETERMINISTIC = "deterministic"
    AI_RUBRIC = "ai_rubric"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class GradingStatus(str, Enum):
    """제출물 전체 채점 상태."""

    GRADED = "graded"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class SubmittedAnswer(BaseModel):
    """응시자가 제출한 단일 문항 답안."""

    question_id: str = Field(min_length=1, max_length=120)
    answer: JsonValue = None

    @field_validator("answer")
    @classmethod
    def validate_answer_size(cls, value: JsonValue) -> JsonValue:
        """비정상적으로 큰 답안이 AI 채점 비용을 폭증시키지 않게 막는다."""
        if len(str(value)) > 20000:
            raise ValueError("answer는 20000자를 초과할 수 없다.")
        return value


class GradeSubmissionRequest(BaseModel):
    """Spring이 FastAPI 채점 엔진에 넘기는 제출물."""

    attempt_id: str = Field(min_length=1, max_length=120)
    exam_id: str = Field(min_length=1, max_length=120)
    answer_key_seal: str = Field(min_length=46, max_length=128)
    questions: list[Question] = Field(min_length=1, max_length=100)
    submitted_answers: list[SubmittedAnswer] = Field(min_length=0, max_length=100)
    pass_percentage: float = Field(default=60.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def validate_answer_targets(self) -> "GradeSubmissionRequest":
        """존재하지 않는 문항에 대한 답안 제출을 계약 위반으로 처리한다."""
        question_ids = {question.question_id for question in self.questions}
        answer_ids = {answer.question_id for answer in self.submitted_answers}
        unknown_ids = sorted(answer_ids - question_ids)
        if unknown_ids:
            joined = ", ".join(unknown_ids)
            raise ValueError(f"알 수 없는 question_id 답안: {joined}")
        if len(answer_ids) != len(self.submitted_answers):
            raise ValueError("동일 question_id 답안을 중복 제출할 수 없다.")
        if len(question_ids) != len(self.questions):
            raise ValueError("동일 question_id 문항을 중복 제출할 수 없다.")
        return self


class RubricCriterionResult(BaseModel):
    """AI 루브릭 채점의 세부 기준별 결과."""

    criterion: str = Field(min_length=1, max_length=200)
    score: float = Field(ge=0.0)
    max_score: float = Field(gt=0.0)
    reason: str = Field(min_length=1, max_length=1000)


class QuestionGradeResult(BaseModel):
    """문항 하나의 채점 결과."""

    question_id: str
    template_id: str
    score: float = Field(ge=0.0)
    max_score: float = Field(gt=0.0)
    is_correct: bool
    grading_mode: GradingMode
    feedback: str
    rubric_breakdown: list[RubricCriterionResult] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    needs_manual_review: bool = False


class GradeSubmissionResponse(BaseModel):
    """제출물 전체 채점 결과."""

    attempt_id: str
    exam_id: str
    total_score: float = Field(ge=0.0)
    max_score: float = Field(gt=0.0)
    percentage: float = Field(ge=0.0, le=100.0)
    passed: bool
    grading_status: GradingStatus
    graded_at: datetime
    results: list[QuestionGradeResult]
