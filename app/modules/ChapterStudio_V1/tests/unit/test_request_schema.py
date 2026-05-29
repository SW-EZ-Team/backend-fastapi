from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.ChapterStudio_V1.schemas.request import ChapterRequest


def test_chapter_request_accepts_boundaries() -> None:
    req = ChapterRequest(lesson_id="lesson-1")

    assert req.lesson_id == "lesson-1"


@pytest.mark.parametrize("lesson_id", ["", "x" * 121])
def test_chapter_request_rejects_bad_lesson_id(lesson_id: str) -> None:
    with pytest.raises(ValidationError):
        ChapterRequest(lesson_id=lesson_id)


def test_chapter_request_is_strict() -> None:
    with pytest.raises(ValidationError):
        ChapterRequest(lesson_id=123)
