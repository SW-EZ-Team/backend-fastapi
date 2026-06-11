from __future__ import annotations

import json
import re

import pytest

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.db.public_persistence import _insert_public_assignment
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState

_PLACEHOLDER = re.compile(r"\$(\d+)")


class FakeConnection:
    """execute 호출을 기록하고 플레이스홀더 개수와 인자 개수가 맞는지 검증하는 대역이다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, query: str, *args: object) -> object:
        expected = max((int(match) for match in _PLACEHOLDER.findall(query)), default=0)
        assert len(args) == expected, query
        self.calls.append((query, args))
        return "OK"


@pytest.mark.anyio
async def test_insert_public_assignment_maps_columns() -> None:
    """user_id=course owner, status='active', course_id=tutoring_id, chapter_id=lesson_id 매핑을 확인한다."""
    conn = FakeConnection()

    await _insert_public_assignment(conn, _context(), _state())

    query, args = conn.calls[-1]
    assert "INSERT INTO public.assignment" in query
    # id ← new_id("asg"), Spring chk_asg_id 정규식과 동일한 형식이어야 한다.
    assert re.fullmatch(r"asg_[0-9A-Z]{26}", str(args[0]))
    assert args[1] == "user-1"  # user_id ← context.user_id (NOT NULL)
    assert args[2] == "tutoring-1"  # course_id ← context.tutoring_id
    assert args[3] == "lesson-1"  # chapter_id ← context.lesson_id
    assert args[4] == "active"  # status (NOT NULL)
    assert args[5] == "리스트 컴프리헨션 변환"  # title ← assignment_meta.title
    assert args[6] == "for 문을 리스트 컴프리헨션으로 바꾸세요."  # description ← assignment_seed
    assert args[7] == 1  # total_questions ← len(steps)
    assert json.loads(str(args[8])) == ["for 문을 컴프리헨션으로 변환합니다."]  # questions ← JSON(steps)


@pytest.mark.anyio
async def test_insert_public_assignment_total_questions_falls_back_to_one_when_steps_empty() -> None:
    """steps가 비면 total_questions가 NOT NULL 보정으로 1이 되는지 확인한다."""
    conn = FakeConnection()
    state = _state()
    state["assignment_meta"] = {
        "title": "단일 과제",
        "assignment_format": "text",
        "steps": [],
    }

    await _insert_public_assignment(conn, _context(), state)

    _query, args = conn.calls[-1]
    assert args[7] == 1
    assert json.loads(str(args[8])) == []


@pytest.mark.anyio
async def test_insert_public_assignment_title_falls_back_to_first_line() -> None:
    """assignment_meta에 title이 없으면 prompt 첫 줄을 제목으로 쓴다."""
    conn = FakeConnection()
    state = _state()
    state["assignment_seed"] = "첫 줄 제목\n둘째 줄 본문"
    state["assignment_meta"] = {"steps": ["1단계", "2단계", "3단계"]}

    await _insert_public_assignment(conn, _context(), state)

    _query, args = conn.calls[-1]
    assert args[5] == "첫 줄 제목"
    assert args[7] == 3  # steps 3개 → total_questions=3


def _context() -> GenerationContext:
    return GenerationContext(
        lesson_id="lesson-1",
        tutoring_id="tutoring-1",
        user_id="user-1",
        curriculum_plan_id="curriculum-1",
        topic="파이썬 리스트 컴프리헨션",
        chapter_title="리스트 컴프리헨션",
        chapter_brief="반복과 조건을 한 줄 표현으로 이해한다.",
        slide_count=10,
    )


def _state() -> ChapterStudioState:
    return {
        "assignment_seed": "for 문을 리스트 컴프리헨션으로 바꾸세요.",
        "assignment_meta": {
            "title": "리스트 컴프리헨션 변환",
            "assignment_format": "코드 변환",
            "expected_minutes": 25,
            "steps": ["for 문을 컴프리헨션으로 변환합니다."],
            "rubric": ["동작이 같다.", "설명이 충분하다."],
        },
    }
