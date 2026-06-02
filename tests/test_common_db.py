"""공용 DB 풀의 graceful startup 동작을 검증한다."""
from __future__ import annotations

from types import TracebackType
from typing import Iterator, cast

import asyncpg
import pytest
from fastapi import HTTPException

import common.db as common_db


class _FakeConnection:
    """테스트용 커넥션 객체."""


class _FakeAcquireContext:
    """asyncpg Pool.acquire()가 반환하는 컨텍스트 매니저 대역."""

    async def __aenter__(self) -> asyncpg.Connection:
        return cast(asyncpg.Connection, _FakeConnection())

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _FakePool:
    """테스트용 pool 객체."""

    def acquire(self) -> _FakeAcquireContext:
        return _FakeAcquireContext()

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_db_state() -> Iterator[None]:
    """테스트 사이에 전역 pool 상태가 새지 않게 초기화한다."""
    common_db._DB_STATE["pool"] = None
    yield
    common_db._DB_STATE["pool"] = None


@pytest.mark.asyncio
async def test_init_pool_logs_and_does_not_raise_when_database_is_unready(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DATABASE_URL이 있어도 DB 미기동이면 startup 예외 없이 로그만 남긴다."""
    attempts: list[str] = []
    settings: list[dict[str, str]] = []

    async def fail_create_pool(
        dsn: str,
        min_size: int,
        max_size: int,
        server_settings: dict[str, str],
    ) -> asyncpg.Pool:
        attempts.append(dsn)
        settings.append(server_settings)
        raise OSError("테스트용 DB 연결 실패")

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@127.0.0.1:1/app")
    monkeypatch.setenv("DB_POOL_INIT_RETRIES", "2")
    monkeypatch.setenv("DB_POOL_INIT_BACKOFF_SEC", "0")
    monkeypatch.setenv("DB_POOL_INIT_MAX_BACKOFF_SEC", "0")
    monkeypatch.setattr(common_db.asyncpg, "create_pool", fail_create_pool)

    await common_db.init_pool()

    assert attempts == ["postgresql://user:pass@127.0.0.1:1/app"] * 2
    assert settings == [{"search_path": "chapter_studio,public"}] * 2
    assert common_db._DB_STATE["pool"] is None
    assert "DATABASE_URL이 설정됐지만 DB 풀 생성에 실패했습니다" in caplog.text


@pytest.mark.asyncio
async def test_get_connection_retries_lazily_after_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """startup 이후에도 첫 DB 요청에서 lazy pool 생성을 다시 시도한다."""
    attempts: list[str] = []
    settings: list[dict[str, str]] = []
    fake_pool = cast(asyncpg.Pool, _FakePool())

    async def fail_then_succeed(
        dsn: str,
        min_size: int,
        max_size: int,
        server_settings: dict[str, str],
    ) -> asyncpg.Pool:
        attempts.append(dsn)
        settings.append(server_settings)
        if len(attempts) == 1:
            raise OSError("테스트용 DB 연결 실패")
        return fake_pool

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@127.0.0.1:5432/app")
    monkeypatch.setenv("DATABASE_SCHEMA", "custom_schema")
    monkeypatch.setenv("DB_POOL_INIT_RETRIES", "1")
    monkeypatch.setenv("DB_POOL_INIT_BACKOFF_SEC", "0")
    monkeypatch.setenv("DB_POOL_INIT_MAX_BACKOFF_SEC", "0")
    monkeypatch.setattr(common_db.asyncpg, "create_pool", fail_then_succeed)

    await common_db.init_pool()
    assert common_db._DB_STATE["pool"] is None

    async with common_db.get_connection() as conn:
        assert isinstance(conn, _FakeConnection)

    assert attempts == ["postgresql://user:pass@127.0.0.1:5432/app"] * 2
    assert settings == [{"search_path": "custom_schema,public"}] * 2
    assert common_db._DB_STATE["pool"] is fake_pool


def test_server_settings_rejects_unsafe_database_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """공유 풀 search_path에 SQL 조각이 들어가지 않게 차단한다."""
    monkeypatch.setenv("DATABASE_SCHEMA", "; DROP TABLE x;--")

    with pytest.raises(ValueError, match="DATABASE_SCHEMA"):
        common_db._server_settings()


@pytest.mark.asyncio
async def test_get_connection_returns_503_when_database_url_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DATABASE_URL이 없으면 기존처럼 DB 사용 요청에만 503을 반환한다."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        async with common_db.get_connection():
            raise AssertionError("커넥션이 없어야 한다")

    assert exc_info.value.status_code == 503
