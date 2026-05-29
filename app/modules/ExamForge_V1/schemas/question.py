"""모의고사 문제 타입 정의."""
from __future__ import annotations

from pydantic import BaseModel, Field


class QuestionOption(BaseModel):
    """객관식 보기."""

    label: str
    text: str
    is_correct: bool = False


class MatchingPair(BaseModel):
    """연결형 좌-우 쌍."""

    left: str
    right: str


class QuestionDraft(BaseModel):
    """정답 미포함 문제 초안."""

    draft_id: str
    template_id: str
    topic: str
    difficulty: int = Field(ge=1, le=5)
    bloom_level: str = ""
    stem: str
    options: list[QuestionOption] | None = None
    matching_pairs: list[MatchingPair] | None = None
    ordering_items: list[str] | None = None
    blank_positions: list[int] | None = None
    code_snippet: str | None = None


class Question(BaseModel):
    """완성된 문제 - 정답 + 해설 포함."""

    question_id: str
    draft_id: str
    template_id: str
    topic: str
    difficulty: int = Field(ge=1, le=5)
    bloom_level: str
    stem: str
    options: list[QuestionOption] | None = None
    matching_pairs: list[MatchingPair] | None = None
    ordering_items: list[str] | None = None
    correct_ordering: list[str] | None = None
    blank_positions: list[int] | None = None
    blank_answers: list[str] | None = None
    code_snippet: str | None = None
    correct_answer: str
    explanation: str
    source_reference: str = ""
    points: float = 1.0
    distractor_rationale: str | None = None
