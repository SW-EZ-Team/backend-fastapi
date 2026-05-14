from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChapterRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    user_id: str = Field(min_length=1)
    curriculum_id: str = Field(min_length=1)
    chapter_brief: str = Field(min_length=1)
    slide_count: int = Field(ge=10, le=15)
