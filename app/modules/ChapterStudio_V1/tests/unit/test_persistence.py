from __future__ import annotations

import json
import re

import pytest

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.db.persistence import persist_chapter_state
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState

_PLACEHOLDER = re.compile(r"\$(\d+)")


class FakeTransaction:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> None:
        self._conn.events.append("begin")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        self._conn.events.append("end")


class FakeConnection:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    async def execute(self, query: str, *args: object) -> object:
        expected = max((int(match) for match in _PLACEHOLDER.findall(query)), default=0)
        assert len(args) == expected, query
        self.calls.append((query, args))
        return "OK"


@pytest.mark.anyio
async def test_persist_chapter_state_replaces_existing_lesson_rows() -> None:
    conn = FakeConnection()

    await persist_chapter_state(conn, _context(), "chapter_lesson-1", _state())

    queries = [query for query, _args in conn.calls]
    assert conn.events == ["begin", "end"]
    assert queries[0].startswith("DELETE FROM chapter_studio.voice_script_queue")
    assert _has_query(queries, "DELETE FROM chapter_studio.slide")
    assert _has_query(queries, "INSERT INTO chapter_studio.slide")
    assert _has_query(queries, "INSERT INTO chapter_studio.quiz")
    assert _has_query(queries, "INSERT INTO chapter_studio.note")
    assert _has_query(queries, "INSERT INTO chapter_studio.assignment")
    assert _has_query(queries, "INSERT INTO chapter_studio.voice_script")
    assert _has_query(queries, "INSERT INTO chapter_studio.voice_script_queue")
    assert _has_query(queries, "INSERT INTO chapter_studio.lesson_generation_status")
    assert conn.calls[0][1] == ("lesson-1", "chapter_lesson-1")


@pytest.mark.anyio
async def test_persist_chapter_state_writes_meaningful_chapter_studio_slide_title() -> None:
    conn = FakeConnection()

    await persist_chapter_state(conn, _context(), "chapter_lesson-1", _state())

    slide_args = _args_for(conn, "INSERT INTO chapter_studio.slide")
    assert slide_args[8] == "핵심 흐름"


@pytest.mark.anyio
async def test_persist_chapter_state_writes_status_summary() -> None:
    conn = FakeConnection()

    await persist_chapter_state(conn, _context(), "chapter_lesson-1", _state())

    status_args = conn.calls[-1][1]
    assert status_args[:4] == ("lesson-1", "tutoring-1", "chapter_lesson-1", "test-model")
    assert json.loads(str(status_args[4])) == {"slides": 1, "quiz_set": 1, "voice_scripts": 1}


@pytest.mark.anyio
async def test_persist_chapter_state_uses_database_schema_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection()
    monkeypatch.setenv("DATABASE_SCHEMA", "custom_schema")

    await persist_chapter_state(conn, _context(), "chapter_lesson-1", _state())

    queries = [query for query, _args in conn.calls]
    assert _has_query(queries, "INSERT INTO custom_schema.slide")
    assert _has_query(queries, "INSERT INTO custom_schema.lesson_generation_status")


@pytest.mark.anyio
async def test_persist_chapter_state_preserves_assignment_metadata() -> None:
    conn = FakeConnection()

    await persist_chapter_state(conn, _context(), "chapter_lesson-1", _state())

    _query, args = next(call for call in conn.calls if "INSERT INTO chapter_studio.assignment" in call[0])
    assert json.loads(str(args[3])) == {
        "format": "코드 변환",
        "steps": ["for 문을 컴프리헨션으로 변환합니다."],
        "rubric": ["동작이 같다.", "설명이 충분하다."],
    }
    assert args[4] == 25
    assert args[7] == "리스트 컴프리헨션 변환"
    assert args[8] == "코드 변환"


@pytest.mark.anyio
async def test_persist_chapter_state_writes_public_spring_tables() -> None:
    conn = FakeConnection()

    await persist_chapter_state(conn, _context(), "lesson-1", _state())

    slide_args = _args_for(conn, "INSERT INTO public.slide")
    quiz_args = _args_for(conn, "INSERT INTO public.quiz")
    note_args = _args_for(conn, "INSERT INTO public.note")
    assert re.fullmatch(r"sld_[0-9A-Z]{26}", str(slide_args[0]))
    assert slide_args[1:5] == (
        "lesson-1",
        0,
        "핵심 흐름",
        "<iframe srcdoc='<section>1</section>'></iframe>",
    )
    assert slide_args[5:] == (None, 3.5)
    assert re.fullmatch(r"qz_[0-9A-Z]{26}", str(quiz_args[0]))
    assert quiz_args[1:4] == ("lesson-1", 0, "리스트 컴프리헨션의 첫 확인 요소는 무엇인가요?")
    assert json.loads(str(quiz_args[4])) == ["출력식", "파일명", "패키지", "운영체제"]
    assert quiz_args[5:] == (0, "출력식이 새 리스트의 원소를 결정합니다.", slide_args[0])
    assert re.fullmatch(r"nte_[0-9A-Z]{26}", str(note_args[0]))
    assert note_args[1:] == (
        "user-1",
        "tutoring-1",
        "lesson-1",
        "ai_auto",
        "리스트 컴프리헨션 핵심 노트",
        "핵심 노트",
    )


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
        "template_key": "concept_code",
        "generation_model": "test-model",
        "slides": [
            {
                "slide_idx": 0,
                "category": "text",
                "html_content": "<iframe srcdoc='<section>1</section>'></iframe>",
            }
        ],
        "quiz_set": [
            {
                "slide_idx": 0,
                "quiz_idx": 0,
                "question": "리스트 컴프리헨션의 첫 확인 요소는 무엇인가요?",
                "choices": ["출력식", "파일명", "패키지", "운영체제"],
                "answer_idx": 0,
                "difficulty": "이해",
                "explanation": "출력식이 새 리스트의 원소를 결정합니다.",
            }
        ],
        "core_note": "핵심 노트",
        "assignment_seed": "for 문을 리스트 컴프리헨션으로 바꾸세요.",
        "assignment_meta": {
            "title": "리스트 컴프리헨션 변환",
            "assignment_format": "코드 변환",
            "expected_minutes": 25,
            "steps": ["for 문을 컴프리헨션으로 변환합니다."],
            "rubric": ["동작이 같다.", "설명이 충분하다."],
        },
        "voice_scripts": [
            {
                "slide_idx": 0,
                "script_text": "첫 번째 슬라이드의 핵심 흐름입니다.",
                "duration_hint_sec": 3.5,
            }
        ],
    }


def _has_query(queries: list[str], needle: str) -> bool:
    return any(needle in query for query in queries)


def _args_for(conn: FakeConnection, needle: str) -> tuple[object, ...]:
    return next(args for query, args in conn.calls if needle in query)
