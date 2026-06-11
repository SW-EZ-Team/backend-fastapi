from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.common.config import database_schema
from app.modules.ChapterStudio_V1.db.persistence_sql import (
    audio_pending_status_sql,
    failure_status_sql,
    running_status_sql,
)


class StatusConnection(Protocol):
    async def execute(self, query: str, *args: object) -> object:
        """상태 갱신 쿼리를 실행한다."""


async def mark_chapter_running(
    conn: StatusConnection,
    context: GenerationContext,
    chapter_id: str,
) -> None:
    """생성 시작 시점에 진행중(running) 상태 행을 남겨 중간 실패도 추적 가능하게 한다."""
    await conn.execute(
        running_status_sql(database_schema()),
        context.lesson_id,
        context.tutoring_id,
        chapter_id,
    )


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


async def mark_audio_backfill_pending(
    conn: StatusConnection,
    context: GenerationContext,
    result: Mapping[str, object],
    error: Exception | None = None,
) -> None:
    """강의 완료 상태는 유지하되 음성 재시도 필요 마커를 남긴다."""
    summary = _audio_summary(result, error)
    await conn.execute(
        audio_pending_status_sql(database_schema()),
        context.lesson_id,
        json.dumps(summary, ensure_ascii=False),
        _truncate(str(summary["error_message"]), 1000),
    )


def _audio_summary(result: Mapping[str, object], error: Exception | None) -> dict[str, object]:
    error_message = str(error) if error is not None else "일부 슬라이드 음성 백필 실패"
    return {
        "status": "audio_pending",
        "retry_needed": True,
        "updated": result.get("updated", 0),
        "failed": result.get("failed", 0),
        "failed_slide_idxs": result.get("failed_slide_idxs", []),
        "error_type": type(error).__name__ if error is not None else "",
        "error_message": _truncate(error_message, 1000),
    }


def _truncate(value: str, limit: int) -> str:
    return value[:limit]
