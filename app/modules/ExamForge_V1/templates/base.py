"""시험 유형 템플릿 프로토콜."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.ExamForge_V1.schemas.question import QuestionDraft, Question


@runtime_checkable
class ExamTemplate(Protocol):
    """모든 시험 유형의 공통 인터페이스."""

    template_id: str
    locale: str
    category: str
    display_name: str

    def build_generation_prompt(
        self,
        topic: str,
        difficulty: int,
        context: str,
        count: int,
    ) -> str: ...

    def build_distractor_prompt(
        self,
        question_draft: QuestionDraft,
        num_options: int,
    ) -> str: ...

    def build_answer_prompt(
        self,
        question_draft: QuestionDraft,
        source_text: str,
    ) -> str: ...

    def parse_generation_response(
        self, raw_text: str
    ) -> list[QuestionDraft]: ...

    def parse_answer_response(
        self, raw_text: str, draft: QuestionDraft
    ) -> Question: ...

    def validate_structure(self, question: Question) -> list[str]: ...
