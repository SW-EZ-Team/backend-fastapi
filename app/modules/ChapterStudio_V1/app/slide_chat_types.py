from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ChapterStudio_V1.app.frontend_contract import TeacherId

ChatIntent = Literal["definition", "code", "chart", "quiz", "confusion", "transfer"]
ChatEngine = Literal["mock", "gemini"]


class SlideChatRequest(BaseModel):
    """현재 슬라이드에 붙은 채팅 요청이다."""

    model_config = ConfigDict(strict=True, frozen=True)

    topic: str = Field(min_length=1, max_length=2000)
    message: str = Field(min_length=1, max_length=1000)
    engine: ChatEngine = "mock"
    lesson_id: str = Field(default="demo-lesson", min_length=1, max_length=80)
    slide_id: str = Field(default="demo-slide-000", min_length=1, max_length=80)
    slide_idx: int = Field(default=0, ge=0, le=14)
    selected_text: str = Field(default="", max_length=1000)
    playback_sec: float = Field(default=0.0, ge=0.0)
    template: str = Field(default="auto", max_length=80)
    teacher: TeacherId = "owl"
    tone: int = Field(default=50, ge=0, le=100)
    pace: int = Field(default=50, ge=0, le=100)
    tutor_depth: int = Field(default=50, ge=0, le=100)
    socratic: int = Field(default=70, ge=0, le=100)
    audience_level: str = Field(default="일반 학습자", max_length=80)
    weak_points: str = Field(default="", max_length=240)


class SlideChatContext(BaseModel):
    """채팅 AI에 주입할 슬라이드 단위 압축 맥락이다."""

    model_config = ConfigDict(strict=True, frozen=True)

    lesson_id: str
    slide_id: str
    slide_idx: int
    slide_title: str
    slide_role: str
    category: str
    focus: str
    checkpoint: str
    voice_script: str
    note_bullets: list[str]
    weak_points: str
    tutor_style: str
    previous_role: str
    next_role: str
