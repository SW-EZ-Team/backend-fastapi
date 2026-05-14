from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Difficulty = Literal["상", "중", "하", "hard", "medium", "easy", "기억", "이해", "적용", "함정 교정", "실전 판단", "오해"]


class SlideSchema(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    chapter_id: str = Field(min_length=1)
    slide_idx: int = Field(ge=0)
    html_content: str = Field(min_length=1)


class QuizSchema(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    chapter_id: str = Field(min_length=1)
    quiz_idx: int = Field(ge=0)
    question: str = Field(min_length=1)
    choices: list[str] = Field(min_length=4, max_length=4)
    answer_idx: int = Field(ge=0, le=3)
    difficulty: Difficulty


class NoteSchema(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    chapter_id: str = Field(min_length=1)
    content: str = Field(min_length=1)


class AssignmentSchema(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    chapter_id: str = Field(min_length=1)
    content: str = Field(min_length=1)


class VoiceScriptSchema(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    chapter_id: str = Field(min_length=1)
    slide_idx: int = Field(ge=0)
    script_text: str = Field(min_length=1)
    audio_url: str | None = None
    duration_hint_sec: float | None = Field(default=None, gt=0)


class ChapterResponse(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    chapter_id: str = Field(min_length=1)
    slides: list[SlideSchema]
    quizzes: list[QuizSchema]
    note: NoteSchema
    assignment: AssignmentSchema
    voice_scripts: list[VoiceScriptSchema]
