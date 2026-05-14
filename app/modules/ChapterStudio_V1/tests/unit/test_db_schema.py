from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.common.config import _load_env, database_schema


def test_database_schema_rejects_unsafe_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _load_env.cache_clear()
    monkeypatch.setenv("DATABASE_SCHEMA", "; DROP TABLE x;--")

    with pytest.raises(RuntimeError, match="DATABASE_SCHEMA"):
        database_schema()
