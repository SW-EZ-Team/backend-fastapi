from __future__ import annotations

from pathlib import Path


def test_v5_generation_result_contract_migration_exists() -> None:
    sql = _migration_sql()

    assert "ADD COLUMN IF NOT EXISTS chapter_id" in sql
    assert "ADD COLUMN IF NOT EXISTS generation_model" in sql
    assert "ADD COLUMN IF NOT EXISTS result_summary JSONB" in sql
    assert "chk_chapter_studio_generation_status_value" in sql
    assert "idx_chapter_studio_generation_status_chapter" in sql
    assert "idx_chapter_studio_slide_lesson_validation" in sql
    assert "idx_chapter_studio_quiz_lesson_difficulty" in sql


def test_v5_generation_result_contract_is_additive() -> None:
    sql = _migration_sql().upper()

    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert "TRUNCATE" not in sql
    assert "DELETE FROM" not in sql


def _migration_sql() -> str:
    path = _project_root() / "infra/schema/migrations/V5__chapter_studio_generation_result_contract.sql"
    return path.read_text(encoding="utf-8")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[6]
