from __future__ import annotations

from collections.abc import Awaitable
from contextlib import AbstractAsyncContextManager
from importlib import import_module
from types import ModuleType
from typing import Protocol, cast, runtime_checkable

from app.modules.ChapterStudio_V1.common.config import database_schema, database_url


class DbConfigConnection(Protocol):
    async def execute(self, query: str, *args: object) -> object:
        """search_path 설정에 필요한 최소 실행 인터페이스다."""


@runtime_checkable
class DbConnection(Protocol):
    async def fetchval(self, query: str, *args: object) -> object:
        """healthz에서 필요한 최소 DB 호출만 정의한다."""


@runtime_checkable
class DbPool(Protocol):
    def acquire(self) -> AbstractAsyncContextManager[DbConnection]:
        """asyncpg 풀과 테스트 대역이 공유하는 최소 인터페이스다."""

    async def close(self) -> None:
        """풀 종료 인터페이스다."""


class CreatePoolCallable(Protocol):
    def __call__(
        self,
        *,
        dsn: str,
        min_size: int,
        max_size: int,
        init: object,
    ) -> Awaitable[object]:
        """asyncpg.create_pool 호출부에 필요한 키워드 인자만 정의한다."""


def _asyncpg_module() -> ModuleType:
    """타입 스텁이 없는 asyncpg를 런타임 경계 안으로 격리한다."""
    return import_module("asyncpg")


def _create_pool_callable() -> CreatePoolCallable:
    """untyped 외부 함수를 내부 Protocol로 좁힌다."""
    return cast(CreatePoolCallable, getattr(_asyncpg_module(), "create_pool"))


def _asyncpg_exception(name: str) -> type[BaseException]:
    """asyncpg 예외 클래스를 런타임에 검증해 반환한다."""
    value = getattr(_asyncpg_module(), name)
    if not isinstance(value, type) or not issubclass(value, BaseException):
        raise RuntimeError(f"asyncpg 예외 클래스를 찾을 수 없다: {name}")
    return value


def startup_error_types() -> tuple[type[BaseException], ...]:
    """lifespan에서 풀 생성 실패로 간주할 예외만 반환한다."""
    return (OSError, _asyncpg_exception("PostgresError"))


def ping_error_types() -> tuple[type[BaseException], ...]:
    """healthz DB ping 실패로 간주할 예외만 반환한다."""
    return (
        OSError,
        _asyncpg_exception("PostgresError"),
        _asyncpg_exception("InterfaceError"),
    )


async def _init_connection(conn: DbConfigConnection) -> None:
    """풀 커넥션마다 chapter_studio schema를 먼저 보게 한다."""
    schema = database_schema()
    await conn.execute("SELECT set_config('search_path', $1, false)", f"{schema}, public")


async def create_pool(min_size: int = 1, max_size: int = 5) -> DbPool:
    """Phase 1용 작은 asyncpg 풀을 생성한다."""
    pool = await _create_pool_callable()(
        dsn=database_url(),
        min_size=min_size,
        max_size=max_size,
        init=_init_connection,
    )
    if pool is None:
        raise RuntimeError("DB 풀 생성에 실패했다.")
    return cast(DbPool, pool)


async def close_pool(pool: DbPool | None) -> None:
    """FastAPI 종료 시 풀을 정상 종료한다."""
    if pool is not None:
        await pool.close()


async def ping(pool: DbPool) -> None:
    """healthz에서 실제 DB 왕복을 검증한다."""
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
