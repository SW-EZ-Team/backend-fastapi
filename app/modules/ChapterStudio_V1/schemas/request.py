from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChapterRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    lesson_id: str = Field(min_length=1, max_length=120)
