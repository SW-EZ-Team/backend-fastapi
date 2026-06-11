from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.common.config import database_schema
from app.modules.ChapterStudio_V1.db.persistence_sql import (
    assignment_sql,
    delete_queue_sql,
    note_sql,
    queue_sql,
    quiz_sql,
    slide_sql,
    status_sql,
    voice_sql,
)
from app.modules.ChapterStudio_V1.db.persistence_values import (
    first_line as _first_line,
    id_for as _id,
    json_text as _json,
    optional_number as _optional_number,
    optional_records as _optional_records,
    optional_text as _optional_text,
    record_default_int as _record_default_int,
    record_default_str_list as _record_default_str_list,
    record_default_text as _record_default_text,
    record_int as _record_int,
    record_str_list as _record_str_list,
    record_text as _record_text,
    records as _records,
    state_record as _state_record,
    state_text as _state_text,
    summary as _summary,
    voice_rows as _voice_rows,
)
from app.modules.ChapterStudio_V1.db.public_persistence import persist_public_content
from app.modules.ChapterStudio_V1.db.title_fallback import slide_title_from_context
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState, StateRecord

_LOG = logging.getLogger(__name__)


class PersistenceConnection(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[object]:
        """asyncpg transaction과 테스트 대역이 공유하는 최소 인터페이스다."""

    async def execute(self, query: str, *args: object) -> object:
        """저장 쿼리를 실행한다."""


async def persist_chapter_state(
    conn: PersistenceConnection,
    context: GenerationContext,
    chapter_id: str,
    state: ChapterStudioState,
) -> None:
    """생성 결과를 lesson_id 기준으로 재시도 가능하게 저장한다."""
    schema = database_schema()
    lesson_id = context.lesson_id
    # 진단용 카운트: 어느 INSERT가 마지막으로 시도된 단계인지 로그로 추적하기 위함이다.
    slide_count = len(_records(state, "slides"))
    quiz_count = len(_records(state, "quiz_set"))
    voice_count = len(_voice_rows(state))
    step = "시작"
    try:
        async with conn.transaction():
            step = "1/7 기존 삭제"
            _LOG.info("[persist] 1/7 기존 삭제 시작 lessonId=%s", lesson_id)
            await _delete_existing(conn, lesson_id, chapter_id, schema)
            step = "2/7 슬라이드 INSERT"
            _LOG.info("[persist] 2/7 슬라이드 INSERT (%d개) lessonId=%s", slide_count, lesson_id)
            await _insert_slides(conn, context, chapter_id, state, schema)
            step = "3/7 퀴즈 INSERT"
            _LOG.info("[persist] 3/7 퀴즈 INSERT (%d개) lessonId=%s", quiz_count, lesson_id)
            await _insert_quizzes(conn, context, chapter_id, state, schema)
            step = "4/7 노트 INSERT"
            _LOG.info("[persist] 4/7 노트 INSERT lessonId=%s", lesson_id)
            await _insert_note(conn, context, chapter_id, state, schema)
            step = "5/7 과제 INSERT"
            _LOG.info("[persist] 5/7 과제 INSERT lessonId=%s", lesson_id)
            await _insert_assignment(conn, context, chapter_id, state, schema)
            step = "6/7 음성대본 INSERT"
            _LOG.info("[persist] 6/7 음성대본 INSERT (%d개) lessonId=%s", voice_count, lesson_id)
            await _insert_voice_scripts(conn, context, chapter_id, state, schema)
            step = "7/7 public 컨텐츠 저장"
            _LOG.info("[persist] 7/7 public 컨텐츠 저장 lessonId=%s", lesson_id)
            await persist_public_content(conn, context, state)
            step = "7/7 완료 상태 기록"
            _LOG.info("[persist] 7/7 완료 상태 기록 lessonId=%s", lesson_id)
            await _mark_done(conn, context, chapter_id, state, schema)
        _LOG.info("[persist] 저장 완료 lessonId=%s", lesson_id)
    except Exception:
        # 트랜잭션은 롤백되어 0행이 되므로, 어느 단계까지 진행됐는지를 로그로 남겨 원인을 좁힌다.
        # 롤백 동작은 그대로 보존하기 위해 삼키지 않고 재전파한다.
        _LOG.exception("[persist] 트랜잭션 실패 — 마지막 단계=%s lessonId=%s", step, lesson_id)
        raise


async def _delete_existing(conn: PersistenceConnection, lesson_id: str, chapter_id: str, schema: str) -> None:
    await conn.execute(delete_queue_sql(schema), lesson_id, chapter_id)
    for table in ("chapter_audio", "voice_script", "assignment", "note", "quiz", "slide"):
        await conn.execute(f"DELETE FROM {schema}.{table} WHERE lesson_id = $1 OR chapter_id = $2", lesson_id, chapter_id)


async def _insert_slides(conn: PersistenceConnection, context: GenerationContext, chapter_id: str, state: ChapterStudioState, schema: str) -> None:
    drafts = _indexed_optional_records(state, "slide_drafts")
    voices = {_record_int(row, "slide_idx"): row for row in _voice_rows(state)}
    outlines = _indexed_optional_records(state, "slide_outline")
    for row in _records(state, "slides"):
        idx = _record_int(row, "slide_idx")
        await conn.execute(
            slide_sql(schema),
            _id(chapter_id, "slide", idx),
            chapter_id,
            idx,
            _record_text(row, "category"),
            _record_text(row, "html_content"),
            context.tutoring_id,
            context.lesson_id,
            idx,
            _slide_title(drafts.get(idx), row, voices.get(idx, {}), outlines.get(idx), context, idx),
            _state_text(state, "template_key"),
            _json({"warnings": row.get("warnings", [])}),
        )


async def _insert_quizzes(conn: PersistenceConnection, context: GenerationContext, chapter_id: str, state: ChapterStudioState, schema: str) -> None:
    for row in _records(state, "quiz_set"):
        idx = _record_int(row, "quiz_idx") if "quiz_idx" in row else _record_int(row, "slide_idx")
        await conn.execute(
            quiz_sql(schema),
            _id(chapter_id, "quiz", idx),
            chapter_id,
            _record_text(row, "question"),
            _json(_record_str_list(row, "choices")),
            _record_int(row, "answer_idx"),
            _record_text(row, "explanation"),
            _record_text(row, "difficulty"),
            context.tutoring_id,
            context.lesson_id,
            idx,
            _json([_record_int(row, "slide_idx")]),
        )


async def _insert_note(conn: PersistenceConnection, context: GenerationContext, chapter_id: str, state: ChapterStudioState, schema: str) -> None:
    await conn.execute(
        note_sql(schema),
        _id(chapter_id, "note", 0),
        chapter_id,
        _state_text(state, "core_note"),
        context.tutoring_id,
        context.lesson_id,
        _json({"template_key": _state_text(state, "template_key")}),
    )


async def _insert_assignment(conn: PersistenceConnection, context: GenerationContext, chapter_id: str, state: ChapterStudioState, schema: str) -> None:
    prompt = _state_text(state, "assignment_seed")
    meta = _state_record(state, "assignment_meta")
    await conn.execute(
        assignment_sql(schema),
        _id(chapter_id, "assignment", 0),
        chapter_id,
        prompt,
        _json(
            {
                "format": _record_default_text(meta, "assignment_format", "text"),
                "steps": _record_default_str_list(meta, "steps"),
                "rubric": _record_default_str_list(meta, "rubric"),
            }
        ),
        _record_default_int(meta, "expected_minutes", 20),
        context.tutoring_id,
        context.lesson_id,
        _record_default_text(meta, "title", _first_line(prompt)),
        _record_default_text(meta, "assignment_format", "text")[:40],
        _json([]),
        prompt,
    )


async def _insert_voice_scripts(conn: PersistenceConnection, context: GenerationContext, chapter_id: str, state: ChapterStudioState, schema: str) -> None:
    for row in _voice_rows(state):
        idx = _record_int(row, "slide_idx")
        voice_id = _id(chapter_id, "voice", idx)
        audio_url = _optional_text(row, "audio_url")
        await conn.execute(
            voice_sql(schema),
            voice_id,
            chapter_id,
            idx,
            _record_text(row, "script_text"),
            _optional_number(row, "duration_hint_sec"),
            audio_url,
            context.tutoring_id,
            context.lesson_id,
            _id(chapter_id, "slide", idx),
        )
        if audio_url is None:
            await conn.execute(queue_sql(schema), _id(chapter_id, "voice_queue", idx), voice_id)


async def _mark_done(conn: PersistenceConnection, context: GenerationContext, chapter_id: str, state: ChapterStudioState, schema: str) -> None:
    await conn.execute(status_sql(schema), context.lesson_id, context.tutoring_id, chapter_id, _state_text(state, "generation_model"), _json(_summary(state)))


def _indexed_optional_records(state: ChapterStudioState, key: str) -> dict[int, StateRecord]:
    """slide_idx 기준으로 선택적 상태 목록을 빠르게 찾을 수 있게 만든다."""
    return {_record_int(row, "slide_idx"): row for row in _optional_records(state, key)}


def _slide_title(
    draft: StateRecord | None,
    slide: StateRecord,
    voice: StateRecord,
    outline: StateRecord | None,
    context: GenerationContext,
    idx: int,
) -> str:
    """chapter_studio.slide도 public.slide와 같은 내용 기반 제목을 쓴다."""
    return slide_title_from_context(draft, slide, voice, outline, context.chapter_title, idx)
