from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import app.modules.ChapterStudio_V1.app.main as main_module


async def _raise_pool_error() -> main_module.DbPool:
    raise OSError("테스트용 DB 연결 실패")


def test_healthz_returns_503_when_pool_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "create_pool", _raise_pool_error)

    with TestClient(main_module.app) as client:
        response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "down", "modal": "skipped"}
