"""asyncpg 커넥션 풀 관리 모듈.

앱 lifespan에서 init_pool / close_pool 을 호출한다.
DATABASE_URL 미설정 시 풀은 None이며, get_connection()은 503을 반환한다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from types import TracebackType
from typing import AsyncIterator

import asyncpg
from fastapi import HTTPException

_LOG = logging.getLogger(__name__)
_POOL_CREATE_ERRORS = (asyncpg.PostgresError, OSError, TimeoutError, ValueError)
_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# global 대신 딕셔너리 홀더 패턴 사용 — 모듈 수준 변수 재바인딩 부작용 방지
_DB_STATE: dict[str, asyncpg.Pool | None] = {"pool": None}
_DB_POOL_LOCK = asyncio.Lock()


def _env_int(name: str, default: int, minimum: int) -> int:
    """환경변수 정수값을 안전하게 읽고 잘못된 값이면 기본값을 쓴다."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        _LOG.warning("%s 값이 정수가 아니어서 기본값 %s를 사용합니다.", name, default)
        return default
    return max(parsed, minimum)


def _env_float(name: str, default: float, minimum: float) -> float:
    """환경변수 실수값을 안전하게 읽고 잘못된 값이면 기본값을 쓴다."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        _LOG.warning("%s 값이 숫자가 아니어서 기본값 %.2f를 사용합니다.", name, default)
        return default
    return max(parsed, minimum)


def _exc_info(
    error: BaseException,
) -> tuple[type[BaseException], BaseException, TracebackType | None]:
    """logging.exc_info에 전달할 예외 튜플을 만든다."""
    return (type(error), error, error.__traceback__)


async def _sleep_before_retry(delay_sec: float) -> None:
    """테스트에서는 0초 백오프로 즉시 재시도할 수 있게 분리한다."""
    if delay_sec > 0:
        await asyncio.sleep(delay_sec)


async def _create_pool_with_retry(dsn: str, reason: str) -> asyncpg.Pool | None:
    """DB가 늦게 뜨는 컨테이너 순서를 고려해 제한된 횟수만 재시도한다."""
    attempts = _env_int("DB_POOL_INIT_RETRIES", default=5, minimum=1)
    delay_sec = _env_float("DB_POOL_INIT_BACKOFF_SEC", default=1.0, minimum=0.0)
    max_delay_sec = _env_float("DB_POOL_INIT_MAX_BACKOFF_SEC", default=5.0, minimum=0.0)
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await asyncpg.create_pool(
                dsn,
                min_size=2,
                max_size=10,
                server_settings=_server_settings(),
            )
        except _POOL_CREATE_ERRORS as exc:
            last_error = exc
            if attempt == attempts:
                break
            _LOG.warning(
                "DB 풀 생성 실패(%s/%s, reason=%s). %.2f초 후 재시도합니다.",
                attempt,
                attempts,
                reason,
                delay_sec,
                exc_info=_exc_info(exc),
            )
            await _sleep_before_retry(delay_sec)
            delay_sec = min(delay_sec * 2, max_delay_sec)

    if last_error is not None:
        _LOG.error(
            "DATABASE_URL이 설정됐지만 DB 풀 생성에 실패했습니다(reason=%s). "
            "앱은 계속 실행되며 다음 DB 요청에서 lazy 재연결을 시도합니다.",
            reason,
            exc_info=_exc_info(last_error),
        )
    return None


def _server_settings() -> dict[str, str]:
    """공유 풀의 unqualified 쿼리가 ChapterStudio 스키마를 먼저 보게 한다."""
    return {"search_path": f"{_database_schema()},public"}


def _database_schema() -> str:
    """DATABASE_SCHEMA를 안전한 PostgreSQL 식별자 형태로 제한한다."""
    schema = os.getenv("DATABASE_SCHEMA") or "chapter_studio"
    if _SCHEMA_RE.fullmatch(schema) is None:
        raise ValueError("DATABASE_SCHEMA 형식이 안전하지 않다.")
    return schema


async def _ensure_pool(reason: str) -> asyncpg.Pool | None:
    """풀 없을 때만 직렬화해서 생성하고, 실패해도 startup을 막지 않는다."""
    pool = _DB_STATE["pool"]
    if pool is not None:
        return pool

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        return None

    async with _DB_POOL_LOCK:
        pool = _DB_STATE["pool"]
        if pool is not None:
            return pool
        pool = await _create_pool_with_retry(dsn, reason)
        _DB_STATE["pool"] = pool
        return pool


async def init_pool() -> None:
    """DATABASE_URL이 설정된 경우 startup에서 풀 생성을 시도한다."""
    await _ensure_pool("startup")


async def close_pool() -> None:
    """앱 종료 시 풀을 닫는다."""
    pool = _DB_STATE["pool"]
    if pool is not None:
        await pool.close()
        _DB_STATE["pool"] = None


@asynccontextmanager
async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    """풀에서 커넥션을 빌려 쓰고 반환하는 컨텍스트 매니저."""
    pool = await _ensure_pool("request")
    if pool is None:
        raise HTTPException(status_code=503, detail="DB 연결을 사용할 수 없습니다.")
    async with pool.acquire() as conn:
        yield conn
