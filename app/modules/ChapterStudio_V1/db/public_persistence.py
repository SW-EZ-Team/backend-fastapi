from __future__ import annotations

from typing import Protocol

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.common.ids import new_id
from app.modules.ChapterStudio_V1.db.persistence_sql import (
    public_delete_note_sql,
    public_delete_quiz_sql,
    public_delete_slide_sql,
    public_note_sql,
    public_quiz_sql,
    public_slide_sql,
)
from app.modules.ChapterStudio_V1.db.persistence_values import (
    json_text as _json,
    optional_number as _optional_number,
    optional_records as _optional_records,
    optional_text as _optional_text,
    record_int as _record_int,
    record_str_list as _record_str_list,
    record_text as _record_text,
    records as _records,
    state_text as _state_text,
    voice_rows as _voice_rows,
)
from app.modules.ChapterStudio_V1.db.title_fallback import slide_title_from_context
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState, StateRecord

_AI_NOTE_TYPE = "ai_auto"


class PublicPersistenceConnection(Protocol):
    async def execute(self, query: str, *args: object) -> object:
        """public 스키마 저장 쿼리를 실행한다."""


async def persist_public_content(
    conn: PublicPersistenceConnection,
    context: GenerationContext,
    state: ChapterStudioState,
) -> None:
    """Spring 조회용 public.slide/quiz/note를 lesson_id 기준으로 재기록한다."""
    await _delete_existing_public(conn, context)
    slide_ids = await _insert_public_slides(conn, context, state)
    await _insert_public_quizzes(conn, context, state, slide_ids)
    await _insert_public_note(conn, context, state)


async def _delete_existing_public(conn: PublicPersistenceConnection, context: GenerationContext) -> None:
    await conn.execute(public_delete_quiz_sql(), context.lesson_id)
    await conn.execute(
        public_delete_note_sql(),
        context.user_id,
        context.tutoring_id,
        context.lesson_id,
        _AI_NOTE_TYPE,
    )
    await conn.execute(public_delete_slide_sql(), context.lesson_id)


async def _insert_public_slides(
    conn: PublicPersistenceConnection,
    context: GenerationContext,
    state: ChapterStudioState,
) -> dict[int, str]:
    drafts = {_record_int(row, "slide_idx"): row for row in _optional_records(state, "slide_drafts")}
    voices = {_record_int(row, "slide_idx"): row for row in _voice_rows(state)}
    outlines = {_record_int(row, "slide_idx"): row for row in _optional_records(state, "slide_outline")}
    slide_ids: dict[int, str] = {}
    for row in _records(state, "slides"):
        idx = _record_int(row, "slide_idx")
        slide_id = new_id("sld")
        voice = voices.get(idx, {})
        duration = _optional_number(voice, "duration_hint_sec")
        await conn.execute(
            public_slide_sql(),
            slide_id,
            context.lesson_id,
            idx,
            _slide_title(drafts.get(idx), row, voice, outlines.get(idx), context, idx),
            _record_text(row, "html_content"),
            _optional_text(voice, "audio_url"),
            duration if duration is not None else 0.0,
        )
        slide_ids[idx] = slide_id
    return slide_ids


async def _insert_public_quizzes(
    conn: PublicPersistenceConnection,
    context: GenerationContext,
    state: ChapterStudioState,
    slide_ids: dict[int, str],
) -> None:
    for row in _records(state, "quiz_set"):
        idx = _record_int(row, "quiz_idx") if "quiz_idx" in row else _record_int(row, "slide_idx")
        slide_idx = _record_int(row, "slide_idx")
        await conn.execute(
            public_quiz_sql(),
            new_id("qz"),
            context.lesson_id,
            idx,
            _record_text(row, "question"),
            _json(_record_str_list(row, "choices")),
            _record_int(row, "answer_idx"),
            _record_text(row, "explanation"),
            slide_ids[slide_idx],
        )


async def _insert_public_note(
    conn: PublicPersistenceConnection,
    context: GenerationContext,
    state: ChapterStudioState,
) -> None:
    await conn.execute(
        public_note_sql(),
        new_id("nte"),
        context.user_id,
        context.tutoring_id,
        context.lesson_id,
        _AI_NOTE_TYPE,
        f"{context.chapter_title} 핵심 노트"[:200],
        _state_text(state, "core_note"),
    )


def _slide_title(
    draft: StateRecord | None,
    slide: StateRecord,
    voice: StateRecord,
    outline: StateRecord | None,
    context: GenerationContext,
    idx: int,
) -> str:
    return slide_title_from_context(draft, slide, voice, outline, context.chapter_title, idx)
