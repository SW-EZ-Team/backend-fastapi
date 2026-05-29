"""asyncpg 커넥션 풀 관리 모듈.

앱 lifespan에서 init_pool / close_pool 을 호출한다.
DATABASE_URL 미설정 시 풀은 None이며, get_connection()은 503을 반환한다.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg
from fastapi import HTTPException

# global 대신 딕셔너리 홀더 패턴 사용 — 모듈 수준 변수 재바인딩 부작용 방지
_DB_STATE: dict[str, asyncpg.Pool | None] = {"pool": None}


async def init_pool() -> None:
    """DATABASE_URL이 설정된 경우 asyncpg 풀을 생성한다."""
    dsn = os.getenv("DATABASE_URL")
    if dsn is None:
        return
    _DB_STATE["pool"] = await asyncpg.create_pool(dsn, min_size=2, max_size=10)


async def close_pool() -> None:
    """앱 종료 시 풀을 닫는다."""
    pool = _DB_STATE["pool"]
    if pool is not None:
        await pool.close()
        _DB_STATE["pool"] = None


@asynccontextmanager
async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    """풀에서 커넥션을 빌려 쓰고 반환하는 컨텍스트 매니저."""
    pool = _DB_STATE["pool"]
    if pool is None:
        raise HTTPException(status_code=503, detail="DB 연결을 사용할 수 없습니다.")
    async with pool.acquire() as conn:
        yield conn
