from __future__ import annotations

import json
from typing import Protocol

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.common.config import database_schema
from app.modules.ChapterStudio_V1.db.persistence_sql import failure_status_sql


class StatusConnection(Protocol):
    async def execute(self, query: str, *args: object) -> object:
        """상태 갱신 쿼리를 실행한다."""


async def mark_chapter_failed(
    conn: StatusConnection,
    context: GenerationContext,
    chapter_id: str,
    stage: str,
    error: Exception,
) -> None:
    """생성 실패를 Spring 폴링용 상태 행에 남긴다."""
    error_message = _truncate(str(error), 1000)
    summary = {
        "error_type": type(error).__name__,
        "error_message": error_message,
    }
    await conn.execute(
        failure_status_sql(database_schema()),
        context.lesson_id,
        context.tutoring_id,
        stage,
        chapter_id,
        json.dumps(summary, ensure_ascii=False),
        error_message,
    )


def _truncate(value: str, limit: int) -> str:
    return value[:limit]
