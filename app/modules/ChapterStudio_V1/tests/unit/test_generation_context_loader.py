from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.modules.ChapterStudio_V1.db.generation_context_loader import (
    GENERATION_CONTEXT_SQL,
    generation_context_sql,
    load_generation_context,
    row_to_generation_context,
)
from app.modules.ChapterStudio_V1.common.errors import ConversionError, StorageError


class FakeConnection:
    def __init__(self, row: Mapping[str, object] | None) -> None:
        self.row = row
        self.query = ""
        self.args: tuple[object, ...] = ()

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None:
        self.query = query
        self.args = args
        return self.row


def test_generation_context_sql_uses_parameterized_lesson_id() -> None:
    assert "WHERE cu.lesson_id = $1" in GENERATION_CONTEXT_SQL
    assert "{lesson_id}" not in GENERATION_CONTEXT_SQL


def test_generation_context_sql_uses_configured_schema() -> None:
    sql = generation_context_sql("custom_schema")

    assert "FROM custom_schema.curriculum_unit cu" in sql
    assert "JOIN custom_schema.curriculum_plan cp" in sql
    assert "LEFT JOIN public.course co ON co.id = cp.tutoring_id" in sql
    assert "LEFT JOIN custom_schema.lesson_generation_status lgs" in sql
    assert "COALESCE(co.tutor_id, '') AS tutor_id" in sql


@pytest.mark.asyncio
async def test_load_generation_context_reads_db_snapshot() -> None:
    conn = FakeConnection(_row())
    context = await load_generation_context(conn, "lesson-1")

    assert conn.args == ("lesson-1",)
    assert context.lesson_id == "lesson-1"
    assert context.template == "statistics_inference"
    assert context.to_generation_input().teacher == "fox"
    assert context.to_generation_input().use_formal_speech is False
    assert context.to_generation_input().use_emoji is True
    assert context.to_generation_input().tutor_name == "냥 튜터"
    assert context.tutor_id == "tut_00000000000000PRESET_CAT01"
    assert context.to_generation_input().tutor_id == "tut_00000000000000PRESET_CAT01"


@pytest.mark.asyncio
async def test_load_generation_context_uses_database_schema_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection(_row())
    monkeypatch.setenv("DATABASE_SCHEMA", "custom_schema")

    await load_generation_context(conn, "lesson-1")

    assert "FROM custom_schema.curriculum_unit cu" in conn.query


@pytest.mark.asyncio
async def test_load_generation_context_reads_reference_book_context() -> None:
    row = dict(_row())
    row["generation_context"] = {
        "reference_book_context": {
            "source_title": "통계 교재",
            "query": "p-value",
            "page_count": 100,
            "ocr_model": "paddleocr-ppv4",
            "hits": [
                {
                    "page": 42,
                    "snippet": "p-value는 귀무가설 아래 확률이다.",
                    "score": 3.0,
                    "source_title": "통계 교재",
                    "matched_terms": ["p-value"],
                }
            ],
        }
    }
    context = await load_generation_context(FakeConnection(row), "lesson-1")

    assert context.reference_book_context is not None
    assert context.to_generation_input().reference_book_context is not None
    assert context.reference_book_context.hits[0].page == 42


@pytest.mark.asyncio
async def test_load_generation_context_missing_row_raises_storage_error() -> None:
    conn = FakeConnection(None)
    with pytest.raises(StorageError):
        await load_generation_context(conn, "missing")


def test_row_to_generation_context_rejects_invalid_source_mode() -> None:
    row = dict(_row())
    row["source_mode"] = "link"
    with pytest.raises(ConversionError):
        row_to_generation_context(row)


def test_row_to_generation_context_uses_safe_defaults() -> None:
    row = dict(_row())
    row["generation_context"] = {}
    context = row_to_generation_context(row)

    assert context.duration_days == 30
    assert context.teacher == "owl"
    assert context.slide_count == 12
    assert context.use_formal_speech is True
    assert context.use_emoji is False
    assert context.tutor_name == ""


def _row() -> Mapping[str, object]:
    return {
        "lesson_id": "lesson-1",
        "tutoring_id": "tutoring-1",
        "user_id": "user-1",
        "curriculum_plan_id": "plan-1",
        "topic": "p-value와 신뢰구간",
        "source_mode": "topic",
        "pdf_file_name": "",
        "chapter_title": "p-value와 신뢰구간",
        "chapter_brief": "통계 추론의 핵심 관점",
        "learning_goal": "검정과 추정을 분리해 이해",
        "slide_count": 12,
        "template": "statistics_inference",
        "tutor_id": "tut_00000000000000PRESET_CAT01",
        "generation_context": {
            "duration_days": 60,
            "teacher": "fox",
            "tone": 70,
            "pace": 45,
            "tutor_depth": 80,
            "socratic": 75,
            "audience_level": "통계 입문자",
            "weak_points": "표본분포",
            "use_formal_speech": False,
            "use_emoji": True,
            "tutor_name": "냥 튜터",
            "tutor_tagline": "친근한 말투 · 비유 잘 씀",
            "is_default_tutor": True,
            "voice_sample_url": "",
        },
    }
