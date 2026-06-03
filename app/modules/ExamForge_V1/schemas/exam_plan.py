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
    # plan-first 보장: 블루프린트 단계에서 미리 배정한 정답 위치 분포
    # key = 정답 0-index 위치, value = 해당 위치에 배정된 목표 문항 수
    # 검증 게이트에서 실제 분포와 비교해 편차 0을 강제한다
    answer_position_plan: dict[int, int] = {}
