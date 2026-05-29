"""시험 계획 타입."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TypeAllocation(BaseModel):
    """유형별 문제 배분."""

    template_id: str
    count: int = Field(ge=1)
    difficulty_distribution: dict[int, int]
    points_per_question: float = 1.0


class ExamPlan(BaseModel):
    """시험 전체 구성."""

    exam_title: str
    subject: str
    total_questions: int
    total_points: float
    time_limit_minutes: int
    locale: str
    category: str
    type_allocations: list[TypeAllocation]
    topic_weights: dict[str, float]
    passing_score: float = 60.0
    bloom_distribution: dict[str, float] = {}
