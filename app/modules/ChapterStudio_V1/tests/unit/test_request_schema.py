from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.ChapterStudio_V1.schemas.request import ChapterRequest


def test_chapter_request_accepts_boundaries() -> None:
    req = ChapterRequest(
        user_id="u1",
        curriculum_id="c1",
        chapter_brief="정렬 알고리즘",
        slide_count=15,
    )

    assert req.slide_count == 15


@pytest.mark.parametrize("slide_count", [9, 16])
def test_chapter_request_rejects_out_of_range(slide_count: int) -> None:
    with pytest.raises(ValidationError):
        ChapterRequest(
            user_id="u1",
            curriculum_id="c1",
            chapter_brief="정렬 알고리즘",
            slide_count=slide_count,
        )


def test_chapter_request_is_strict() -> None:
    with pytest.raises(ValidationError):
        ChapterRequest(
            user_id="u1",
            curriculum_id="c1",
            chapter_brief="정렬 알고리즘",
            slide_count="10",
        )
