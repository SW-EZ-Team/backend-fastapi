from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app.modules.ChapterStudio_V1.app.db import (
    DbPool,
    close_pool,
    create_pool,
    ping,
)
from app.modules.ChapterStudio_V1.app.routers.demo_chapter_studio import router as demo_router
from app.modules.ChapterStudio_V1.ai_connectors.registry import close_all as close_connectors
from app.modules.ChapterStudio_V1.common.logging import logger

_STARTUP_ERRORS = (asyncpg.PostgresError, OSError)
_PING_ERRORS = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError)


def _db_pool(app: FastAPI) -> DbPool | None:
    """FastAPI state에서 DB 풀을 안전하게 꺼낸다."""
    pool = getattr(app.state, "db_pool", None)
    if isinstance(pool, DbPool):
        return pool
    return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """앱 시작과 종료 시 DB 풀 생명주기를 관리한다."""
    try:
        app.state.db_pool = await create_pool()
    except _STARTUP_ERRORS as exc:
        logger.exception("DB pool 생성 실패: {}", exc)
        app.state.db_pool = None
    try:
        yield
    finally:
        await close_connectors()
        await close_pool(_db_pool(app))


app = FastAPI(title="ChapterStudio_V1", lifespan=lifespan)

# CORS — 개발 샌드박스 전용, 프로덕션 전환 시 오리진 제한 필요
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(demo_router)


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, str]:
    pool = _db_pool(app)
    if pool is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "db": "down", "modal": "skipped"}

    try:
        await ping(pool)
    except _PING_ERRORS as exc:
        logger.warning("DB ping 실패: {}", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "db": "down", "modal": "skipped"}

    return {"status": "ok", "db": "ok", "modal": "skipped"}
