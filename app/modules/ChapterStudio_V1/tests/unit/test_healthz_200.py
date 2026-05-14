from __future__ import annotations

from types import TracebackType

from fastapi.testclient import TestClient
import pytest

import app.modules.ChapterStudio_V1.app.main as main_module


class FakeAcquire:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakePool:
    def acquire(self) -> FakeAcquire:
        return FakeAcquire()

    async def close(self) -> None:
        return None


async def _create_fake_pool() -> FakePool:
    return FakePool()


async def _ping_ok(pool: main_module.DbPool) -> None:
    return None


def test_healthz_returns_200_when_ping_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "create_pool", _create_fake_pool)
    monkeypatch.setattr(main_module, "ping", _ping_ok)

    with TestClient(main_module.app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "modal": "skipped"}
