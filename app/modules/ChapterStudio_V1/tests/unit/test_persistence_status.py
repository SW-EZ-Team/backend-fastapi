from __future__ import annotations

import json
import re

import pytest

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.db.persistence_status import mark_chapter_failed

_PLACEHOLDER = re.compile(r"\$(\d+)")


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, query: str, *args: object) -> object:
        expected = max((int(match) for match in _PLACEHOLDER.findall(query)), default=0)
        assert len(args) == expected, query
        self.calls.append((query, args))
        return "OK"


@pytest.mark.anyio
async def test_mark_chapter_failed_upserts_failed_status() -> None:
    conn = FakeConnection()

    await mark_chapter_failed(conn, _context(), "chapter_lesson-1", "generate_chapter_state", ValueError("bad payload"))

    query, args = conn.calls[0]
    assert "INSERT INTO chapter_studio.lesson_generation_status" in query
    assert "failed" in query
    assert args[:4] == ("lesson-1", "tutoring-1", "generate_chapter_state", "chapter_lesson-1")
    assert json.loads(str(args[4])) == {"error_type": "ValueError", "error_message": "bad payload"}
    assert args[5] == "bad payload"


def _context() -> GenerationContext:
    return GenerationContext(
        lesson_id="lesson-1",
        tutoring_id="tutoring-1",
        user_id="user-1",
        curriculum_plan_id="curriculum-1",
        topic="파이썬 리스트 컴프리헨션",
        chapter_title="리스트 컴프리헨션",
        slide_count=10,
    )
