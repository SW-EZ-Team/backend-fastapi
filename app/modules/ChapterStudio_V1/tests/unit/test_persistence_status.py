from __future__ import annotations

import json
import re

import pytest

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.db.persistence_status import (
    mark_audio_backfill_pending,
    mark_chapter_failed,
    mark_chapter_progress,
    mark_chapter_running,
)

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


@pytest.mark.anyio
async def test_mark_audio_backfill_pending_merges_retry_marker() -> None:
    conn = FakeConnection()

    await mark_audio_backfill_pending(
        conn,
        _context(),
        {"updated": 9, "failed": 2, "failed_slide_idxs": [1, 3]},
    )

    query, args = conn.calls[0]
    summary = json.loads(str(args[1]))
    assert "UPDATE chapter_studio.lesson_generation_status" in query
    assert "jsonb_build_object('audio_backfill'" in query
    assert args[0] == "lesson-1"
    assert summary["status"] == "audio_pending"
    assert summary["retry_needed"] is True
    assert summary["failed"] == 2
    assert summary["failed_slide_idxs"] == [1, 3]
    assert "음성 백필 실패" in str(args[2])


@pytest.mark.anyio
async def test_mark_chapter_progress_upserts_running_progress() -> None:
    conn = FakeConnection()

    await mark_chapter_progress(
        conn,
        _context(),
        "chapter_lesson-1",
        current_node="generate_lesson",
        completed_nodes=2,
        total_nodes=5,
        progress_percent=55,
    )

    query, args = conn.calls[0]
    assert "INSERT INTO chapter_studio.lesson_generation_status" in query
    assert "'running'" in query
    assert "ON CONFLICT (lesson_id)" in query
    assert args == ("lesson-1", "tutoring-1", "generate_lesson", 2, 5, 55, "chapter_lesson-1")


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


@pytest.mark.anyio
async def test_progress_upsert_guards_done_and_failed_rows() -> None:
    """스테일 진행률 콜백이 done/failed 행을 running으로 역행시키지 않는 가드가 SQL에 있다."""
    conn = FakeConnection()

    await mark_chapter_progress(
        conn,
        _context(),
        "chapter_lesson-1",
        current_node="generate_lesson",
        completed_nodes=2,
        total_nodes=5,
        progress_percent=55,
    )

    query, _args = conn.calls[0]
    # 종결 상태 보호 — 완료/실패 후 도착한 늦은 노드 기록이 상태를 되돌리면 안 된다.
    assert "WHERE" in query
    assert ".status NOT IN ('done', 'failed')" in query


@pytest.mark.anyio
async def test_running_upsert_still_resets_done_rows() -> None:
    """재생성 시작(mark_chapter_running)은 가드 없이 done 행을 running으로 되돌린다."""
    conn = FakeConnection()

    await mark_chapter_running(conn, _context(), "chapter_lesson-1")

    query, _args = conn.calls[0]
    assert "'running'" in query
    assert "NOT IN ('done', 'failed')" not in query
