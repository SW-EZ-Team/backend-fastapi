from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Protocol

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.common.config import database_schema, tts_synth_concurrency
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.db.audio_backfill_sql import (
    AudioBackfillTableColumns,
    AudioUpdatePlan,
    chapter_slide_plan,
    public_slide_plan,
    voice_script_sql,
    voice_update_sql,
)
from app.modules.ChapterStudio_V1.db.generation_context_loader import load_generation_context
from app.modules.ChapterStudio_V1.pipeline.state import StateRecord, StateRecords
from app.modules.ChapterStudio_V1.pipeline.tts_routing import TutorVoiceProfile
from app.modules.ChapterStudio_V1.pipeline.voice_audio import synthesize_voice_audio
from common.db import get_connection

_LOG = logging.getLogger(__name__)

SynthesisOutcome = tuple[StateRecord, StateRecord | Exception]


class AudioBackfillConnection(Protocol):
    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None:
        ...

    async def fetch(self, query: str, *args: object) -> Sequence[Mapping[str, object]]:
        ...

    async def execute(self, query: str, *args: object) -> object:
        ...

async def backfill_lesson_audio(lesson_id: str, tutor_id: str | None = None) -> dict[str, object]:
    """기존 강의를 재생성하지 않고 슬라이드별 튜터 음성만 채운다."""
    schema = database_schema()
    updated = 0
    failed = 0
    async with get_connection() as conn:
        context = await _load_context(conn, lesson_id)
        voice_scripts, invalid_count = _voice_script_records(await conn.fetch(voice_script_sql(schema), lesson_id))
        columns = await _load_columns(conn, schema)
        failed += invalid_count
        profile = _profile(context, tutor_id)
        for script, outcome in await _synthesize_many(voice_scripts, profile):
            if isinstance(outcome, Exception):
                slide_idx = script.get("slide_idx")
                _LOG.warning("[lessons] 음성 백필 실패 — lesson_id=%s, slide_idx=%s, error=%s", lesson_id, slide_idx, outcome)
                failed += 1
                continue
            try:
                touched = await _update_audio_record(conn, schema, columns, lesson_id, outcome)
            except Exception as exc:
                _LOG.warning("[lessons] 음성 백필 실패 — lesson_id=%s, error=%s", lesson_id, exc)
                failed += 1
                continue
            if touched:
                updated += 1
            else:
                failed += 1
    return {"lesson_id": lesson_id, "updated": updated, "failed": failed}

async def _load_context(conn: AudioBackfillConnection, lesson_id: str) -> GenerationContext | None:
    try:
        return await load_generation_context(conn, lesson_id)
    except Exception as exc:
        _LOG.warning("[lessons] 음성 백필 컨텍스트 조회 실패 — 기본 튜터로 진행합니다. lesson_id=%s, error=%s", lesson_id, exc)
        return None

def _profile(context: GenerationContext | None, tutor_id: str | None) -> TutorVoiceProfile:
    use_formal_speech = context.use_formal_speech if context is not None else True
    tutor_tagline = context.tutor_tagline if context is not None else ""
    if tutor_id is not None and tutor_id != "":
        return TutorVoiceProfile(
            tutor_id=tutor_id,
            is_default_tutor=True,
            voice_sample_url="",
            use_formal_speech=use_formal_speech,
            tutor_tagline=tutor_tagline,
        )
    resolved_tutor_id = context.tutor_id if context is not None else ""
    return TutorVoiceProfile(
        tutor_id=resolved_tutor_id,
        is_default_tutor=context.is_default_tutor if context is not None else True,
        voice_sample_url=context.voice_sample_url if context is not None else "",
        use_formal_speech=use_formal_speech,
        tutor_tagline=tutor_tagline,
    )

async def _synthesize_one(script: StateRecord, profile: TutorVoiceProfile) -> StateRecord:
    results = await synthesize_voice_audio([script], tutor_profile=profile)
    if not results:
        raise ConversionError("TTS 결과가 비어 있다.")
    return results[0]

async def _synthesize_many(voice_scripts: StateRecords, profile: TutorVoiceProfile) -> list[SynthesisOutcome]:
    """백필은 슬라이드별 실패를 보존하면서 env 동시성으로 합성한다."""
    semaphore = asyncio.Semaphore(tts_synth_concurrency())

    async def _run(script: StateRecord) -> SynthesisOutcome:
        async with semaphore:
            try:
                return script, await _synthesize_one(script, profile)
            except Exception as exc:
                return script, exc

    return list(await asyncio.gather(*[_run(script) for script in voice_scripts]))

async def _update_audio_record(
    conn: AudioBackfillConnection,
    schema: str,
    columns: AudioBackfillTableColumns,
    lesson_id: str,
    audio: StateRecord,
) -> bool:
    slide_idx = _record_int(audio, "slide_idx")
    audio_url = _record_text(audio, "audio_url")
    duration = _record_number(audio, "duration_hint_sec")
    touched = await _execute_update(conn, voice_update_sql(schema), True, lesson_id, slide_idx, audio_url, duration)
    touched = await _execute_optional(conn, chapter_slide_plan(schema, columns.chapter_slide), lesson_id, slide_idx, audio_url, duration) or touched
    touched = await _execute_optional(conn, public_slide_plan(columns.public_slide), lesson_id, slide_idx, audio_url, duration) or touched
    return touched

async def _execute_optional(
    conn: AudioBackfillConnection,
    plan: AudioUpdatePlan | None,
    lesson_id: str,
    slide_idx: int,
    audio_url: str,
    duration: float,
) -> bool:
    if plan is None:
        return False
    return await _execute_update(conn, plan.query, plan.uses_duration, lesson_id, slide_idx, audio_url, duration)


async def _execute_update(
    conn: AudioBackfillConnection,
    query: str,
    uses_duration: bool,
    lesson_id: str,
    slide_idx: int,
    audio_url: str,
    duration: float,
) -> bool:
    args = (lesson_id, slide_idx, audio_url, duration) if uses_duration else (lesson_id, slide_idx, audio_url)
    result = await conn.execute(query, *args)
    return _updated(result)


async def _load_columns(conn: AudioBackfillConnection, schema: str) -> AudioBackfillTableColumns:
    return AudioBackfillTableColumns(
        chapter_slide=await _table_columns(conn, schema, "slide"),
        public_slide=await _table_columns(conn, "public", "slide"),
    )


async def _table_columns(conn: AudioBackfillConnection, schema: str, table: str) -> set[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = $1 AND table_name = $2",
        schema,
        table,
    )
    return {_row_text(row, "column_name") for row in rows}


def _voice_script_records(rows: Sequence[Mapping[str, object]]) -> tuple[StateRecords, int]:
    records: StateRecords = []
    failed = 0
    for row in rows:
        try:
            records.append({"slide_idx": _row_int(row, "slide_idx"), "script_text": _row_text(row, "script_text")})
        except ConversionError:
            failed += 1
    return records, failed


def _updated(result: object) -> bool:
    text = str(result)
    return not (text.startswith("UPDATE ") and text.endswith(" 0"))


def _record_text(record: StateRecord, key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or value == "":
        raise ConversionError(f"{key} 문자열이 필요하다.")
    return value


def _record_int(record: StateRecord, key: str) -> int:
    value = record.get(key)
    if not isinstance(value, int):
        raise ConversionError(f"{key} 정수가 필요하다.")
    return value


def _record_number(record: StateRecord, key: str) -> float:
    value = record.get(key)
    if not isinstance(value, int | float):
        raise ConversionError(f"{key} 숫자가 필요하다.")
    return float(value)


def _row_text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or value == "":
        raise ConversionError(f"{key} 문자열이 필요하다.")
    return value


def _row_int(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int):
        raise ConversionError(f"{key} 정수가 필요하다.")
    return value
