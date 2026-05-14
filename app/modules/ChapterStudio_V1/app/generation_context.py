from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput
from app.modules.ChapterStudio_V1.app.frontend_contract import DepthLevel, SourceMode, TeacherId
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext


class GenerationContext(BaseModel):
    """DB에서 읽은 강의 생성 입력 스냅샷이다."""

    model_config = ConfigDict(strict=True, frozen=True)

    lesson_id: str = Field(min_length=1)
    tutoring_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    curriculum_plan_id: str = Field(min_length=1)
    topic: str = Field(min_length=1, max_length=2000)
    source_mode: SourceMode = "topic"
    pdf_file_name: str = Field(default="", max_length=160)
    duration_days: int = Field(default=30, ge=1, le=365)
    depth: DepthLevel = "normal"
    teacher: TeacherId = "owl"
    tone: int = Field(default=50, ge=0, le=100)
    pace: int = Field(default=50, ge=0, le=100)
    tutor_depth: int = Field(default=50, ge=0, le=100)
    socratic: int = Field(default=70, ge=0, le=100)
    audience_level: str = Field(default="일반 학습자", max_length=80)
    learning_goal: str = Field(default="핵심 개념 이해와 실습", max_length=160)
    weak_points: str = Field(default="", max_length=240)
    chapter_title: str = Field(default="데모 챕터", max_length=120)
    chapter_brief: str = Field(default="", max_length=400)
    template: str = Field(default="auto", max_length=80)
    slide_count: int = Field(default=12, ge=10, le=15)
    reference_book_context: ReferenceBookContext | None = None

    def to_generation_input(self) -> DemoGenerationInput:
        """현재 demo 생성기와 운영 생성기가 공유하는 입력 모델로 바꾼다."""
        return DemoGenerationInput(
            topic=self.topic,
            source_mode=self.source_mode,
            pdf_file_name=self.pdf_file_name,
            duration_days=self.duration_days,
            depth=self.depth,
            teacher=self.teacher,
            tone=self.tone,
            pace=self.pace,
            tutor_depth=self.tutor_depth,
            socratic=self.socratic,
            audience_level=self.audience_level,
            learning_goal=self.learning_goal,
            weak_points=self.weak_points,
            chapter_title=self.chapter_title,
            chapter_brief=self.chapter_brief,
            reference_book_context=self.reference_book_context,
        )
