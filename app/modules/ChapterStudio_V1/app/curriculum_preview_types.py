from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ChapterStudio_V1.app.frontend_contract import SourceMode, TeacherId

CurriculumEngine = Literal["mock", "codex_cli"]
CurriculumDifficulty = Literal["easy", "medium", "hard"]


class CurriculumPreviewRequest(BaseModel):
    """CourseDetail에 들어갈 커리큘럼 초안 요청이다."""

    model_config = ConfigDict(strict=True, frozen=True)

    title: str = Field(default="AI 과외 커리큘럼", min_length=1, max_length=120)
    topic: str = Field(min_length=1, max_length=2000)
    subject: str = Field(default="자유주제", min_length=1, max_length=80)
    source_type: SourceMode = "topic"
    difficulty: CurriculumDifficulty = "medium"
    lesson_count: int = Field(default=10, ge=10, le=15)
    teacher: TeacherId = "owl"
    engine: CurriculumEngine = "codex_cli"


class CurriculumLesson(BaseModel):
    """커리큘럼의 강의 1개 초안이다."""

    model_config = ConfigDict(strict=True, frozen=True)

    order: int = Field(ge=1, le=15)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=300)
    slide_count: int = Field(ge=10, le=15)
    estimated_minutes: int = Field(ge=10, le=90)
    key_topics: list[str] = Field(min_length=3, max_length=6)
    prerequisite: str | None = Field(default=None, max_length=120)


class SourceAnalysis(BaseModel):
    """PDF/주제 입력에서 뽑은 생성 근거 요약이다."""

    model_config = ConfigDict(strict=True, frozen=True)

    detected_topics: list[str] = Field(min_length=3, max_length=8)
    difficulty_assessment: str = Field(min_length=1, max_length=160)
    recommended_prerequisites: list[str] = Field(default_factory=list, max_length=6)


class CurriculumPreview(BaseModel):
    """프론트 CourseDetail 미리보기와 같은 커리큘럼 응답이다."""

    model_config = ConfigDict(strict=True, frozen=True)

    tutoring_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    status: Literal["CURRICULUM_READY"] = "CURRICULUM_READY"
    confirmed: bool = False
    estimated_total_minutes: int = Field(ge=10)
    lessons: list[CurriculumLesson] = Field(min_length=10, max_length=15)
    source_analysis: SourceAnalysis
