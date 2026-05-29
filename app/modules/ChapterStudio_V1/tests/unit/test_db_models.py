from __future__ import annotations

import re
from pathlib import Path

from app.modules.ChapterStudio_V1.db.models import Base

EXPECTED_TABLES = {
    "slide": {"id", "chapter_id", "index", "category", "html", "css", "created_at"},
    "voice_script": {
        "id",
        "chapter_id",
        "slide_index",
        "text",
        "duration_hint_sec",
        "audio_url",
        "created_at",
    },
    "quiz": {"id", "chapter_id", "question", "choices", "answer_idx", "explanation", "depth", "created_at"},
    "note": {"id", "chapter_id", "html", "created_at"},
    "assignment": {"id", "chapter_id", "prompt", "criteria", "expected_minutes", "created_at", "target_concepts", "weakness_focus", "difficulty_level"},
    "chapter_audio": {"id", "chapter_id", "merged_audio_url", "duration_sec", "created_at"},
    "voice_script_queue": {"id", "voice_script_id", "status", "enqueued_at", "completed_at"},
}


def test_orm_tables_match_v2_sql_columns() -> None:
    sql = _v2_sql()

    assert Base.metadata.schema == "chapter_studio"
    for table_name, expected_columns in EXPECTED_TABLES.items():
        orm_table = Base.metadata.tables[f"chapter_studio.{table_name}"]
        assert set(orm_table.columns.keys()) == expected_columns
        assert _sql_columns(sql, table_name) == expected_columns


def _v2_sql() -> str:
    root = Path(__file__).resolve().parents[6]
    return (root / "infra/schema/migrations/V2__chapter_studio.sql").read_text(encoding="utf-8")


def _sql_columns(sql: str, table_name: str) -> set[str]:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS chapter_studio\.{table_name} \((.*?)\);",
        sql,
        re.DOTALL,
    )
    assert match is not None
    columns: set[str] = set()
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        columns.add(line.split()[0])
    return columns
