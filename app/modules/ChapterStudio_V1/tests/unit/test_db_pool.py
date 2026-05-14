from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.app.db import create_pool
from app.modules.ChapterStudio_V1.common.config import _load_env


@pytest.mark.asyncio
async def test_create_pool_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _load_env.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "")

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        await create_pool()
