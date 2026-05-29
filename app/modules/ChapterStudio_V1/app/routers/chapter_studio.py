"""ChapterStudio V1 — 프로덕션 강의 생성 API 라우터.

Spring Boot가 lesson_id와 생성 파라미터를 전달하면
파이프라인이 슬라이드·퀴즈·노트·과제·음성 대본을 생성해 반환한다.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app.modules.ChapterStudio_V1.ai_connectors.errors import AuthError, ConnectorError, RateLimitError
from app.modules.ChapterStudio_V1.ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from app.modules.ChapterStudio_V1.common.errors import ConversionError, StorageError
from app.modules.ChapterStudio_V1.db.generation_context_loader import load_generation_context
from app.modules.ChapterStudio_V1.db.persistence import persist_chapter_state
from app.modules.ChapterStudio_V1.db.persistence_status import mark_chapter_failed
from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.pipeline.converters import state_to_response
from app.modules.ChapterStudio_V1.pipeline.graph import generate_chapter_state
from app.modules.ChapterStudio_V1.schemas.request import ChapterRequest
from app.modules.ChapterStudio_V1.schemas.response import ChapterResponse
from common.db import get_connection

router = APIRouter(prefix="/api/chapter-studio", tags=["chapter-studio"])
_CHAPTER_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


@router.post("/generate", response_model=ChapterResponse)
async def generate_chapter(request: ChapterRequest) -> ChapterResponse:
    """강의 슬라이드·퀴즈·노트·과제·음성 대본을 AI로 생성한다.

    Spring Boot → POST /api/chapter-studio/generate
    헤더: X-API-Key: <FASTAPI_API_KEY>
    """
    context: GenerationContext | None = None
    chapter_id = _chapter_id(request.lesson_id)
    stage = "load_generation_context"
    try:
        async with get_connection() as conn:
            context = await load_generation_context(conn, request.lesson_id)
        stage = "generate_chapter_state"
        state = await generate_chapter_state(context.to_generation_input())
        stage = "state_to_response"
        response = state_to_response(state, chapter_id)
        stage = "persist_chapter_state"
        async with get_connection() as conn:
            await persist_chapter_state(conn, context, chapter_id, state)
        return response
    except AuthError as exc:
        await _record_failure(context, chapter_id, stage, exc)
        raise HTTPException(status_code=503, detail=f"AI 인증 설정 필요: {exc}") from exc
    except RateLimitError as exc:
        await _record_failure(context, chapter_id, stage, exc)
        raise HTTPException(status_code=429, detail=f"AI 요청 한도 초과: {exc}") from exc
    except ConnectorTimeoutError as exc:
        await _record_failure(context, chapter_id, stage, exc)
        raise HTTPException(status_code=504, detail=f"AI 생성 시간 초과: {exc}") from exc
    except ConnectorError as exc:
        await _record_failure(context, chapter_id, stage, exc)
        raise HTTPException(status_code=502, detail=f"AI 커넥터 오류: {exc}") from exc
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=f"강의 생성 입력 없음: {exc}") from exc
    except ConversionError as exc:
        await _record_failure(context, chapter_id, stage, exc)
        raise HTTPException(status_code=422, detail=f"강의 생성 결과 검증 실패: {exc}") from exc
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        await _record_failure(context, chapter_id, stage, exc)
        raise HTTPException(status_code=500, detail=f"ChapterStudio 파이프라인 실패: {exc}") from exc


def _chapter_id(lesson_id: str) -> str:
    """재시도 요청이 같은 chapter_id를 쓰도록 lesson_id 기반으로 고정한다."""
    return f"chapter_{_CHAPTER_ID_SAFE.sub('_', lesson_id).strip('_') or 'lesson'}"


async def _record_failure(
    context: GenerationContext | None,
    chapter_id: str,
    stage: str,
    exc: Exception,
) -> None:
    if context is None:
        return
    try:
        async with get_connection() as conn:
            await mark_chapter_failed(conn, context, chapter_id, stage, exc)
    except (HTTPException, RuntimeError, ValueError, TypeError, KeyError):
        return
