from __future__ import annotations

from typing import cast

from pydantic import ValidationError

from app.modules.ChapterStudio_V1.app.generation_context import GenerationInput
from app.modules.ChapterStudio_V1.app.reference_books.prompt_blocks import reference_context_prompt
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState, StateRecord, StateRecords
from app.modules.ChapterStudio_V1.pipeline._constants import VALID_DIFFICULTY_VALUES
from app.modules.ChapterStudio_V1.schemas.response import (
    AssignmentSchema,
    ChapterResponse,
    Difficulty,
    NoteSchema,
    QuizSchema,
    SlideSchema,
    VoiceScriptSchema,
)

DbRows = dict[str, StateRecords]


def generation_input_to_initial_state(req: GenerationInput) -> ChapterStudioState:
    """DB generation_context 스냅샷을 파이프라인 초기 State로 변환한다."""
    return {
        "user_id": "",
        "curriculum_id": "",
        "topic": req.topic,
        "source_mode": req.source_mode,
        "pdf_file_name": req.pdf_file_name,
        "duration_days": req.duration_days,
        "depth": req.depth,
        "teacher": req.teacher,
        "tone": req.tone,
        "pace": req.pace,
        "tutor_depth": req.tutor_depth,
        "socratic": req.socratic,
        "audience_level": req.audience_level,
        "learning_goal": req.learning_goal,
        "chapter_brief": req.chapter_brief or req.topic,
        "slide_count": req.slide_count,
        "requested_template": req.template,
        "template_key": "",
        "generation_model": "",
        "enriched_brief": "",
        "weak_points": req.weak_points,
        "reference_context_prompt": reference_context_prompt(req.reference_book_context),
        "slide_outline": [],
        "slide_drafts": [],
        "slides": [],
        "quiz_set": [],
        "core_note": "",
        "assignment_seed": "",
        "assignment_meta": {},
        "voice_scripts": [],
        "voice_audio_files": [],
    }


def state_to_response(state: ChapterStudioState, chapter_id: str) -> ChapterResponse:
    """파이프라인 State를 API 응답 모델로 변환한다."""
    try:
        return ChapterResponse(
            chapter_id=chapter_id,
            slides=_slide_schemas(_records(state, "slides"), chapter_id),
            quizzes=_quiz_schemas(_records(state, "quiz_set"), chapter_id),
            note=NoteSchema(chapter_id=chapter_id, content=_state_text(state, "core_note")),
            assignment=AssignmentSchema(chapter_id=chapter_id, content=_state_text(state, "assignment_seed")),
            voice_scripts=_voice_schemas(
                _merge_voice_audio(_records(state, "voice_scripts"), _optional_records(state, "voice_audio_files")),
                chapter_id,
            ),
        )
    except ValidationError as exc:
        raise ConversionError(str(exc)) from exc


def state_to_db_rows(state: ChapterStudioState, chapter_id: str) -> DbRows:
    """Phase 5 INSERT 입력으로 넘길 행 묶음을 만든다."""
    return {
        "slide": _copy_with_chapter(_records(state, "slides"), chapter_id),
        "quiz": _copy_with_chapter(_records(state, "quiz_set"), chapter_id),
        "note": [{"chapter_id": chapter_id, "content": _state_text(state, "core_note")}],
        "assignment": [{"chapter_id": chapter_id, "content": _state_text(state, "assignment_seed")}],
        "voice_script": _copy_with_chapter(
            _merge_voice_audio(_records(state, "voice_scripts"), _optional_records(state, "voice_audio_files")),
            chapter_id,
        ),
    }


def _records(state: ChapterStudioState, key: str) -> StateRecords:
    value = state.get(key)
    if not isinstance(value, list):
        raise ConversionError(f"{key} 목록이 필요하다.")
    records: StateRecords = []
    for item in value:
        if not isinstance(item, dict):
            raise ConversionError(f"{key} 항목은 dict여야 한다.")
        records.append(cast(StateRecord, item))
    return records


def _optional_records(state: ChapterStudioState, key: str) -> StateRecords:
    if key not in state:
        return []
    return _records(state, key)

def _state_text(state: ChapterStudioState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or value == "":
        raise ConversionError(f"{key} 문자열이 필요하다.")
    return value

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

def _record_str_list(record: StateRecord, key: str) -> list[str]:
    value = record.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConversionError(f"{key} 문자열 목록이 필요하다.")
    return cast(list[str], value)


def _slide_schemas(records: StateRecords, chapter_id: str) -> list[SlideSchema]:
    return [
        SlideSchema(
            chapter_id=chapter_id,
            slide_idx=_record_int(record, "slide_idx"),
            html_content=_record_text(record, "html_content"),
        )
        for record in records
    ]


def _quiz_schemas(records: StateRecords, chapter_id: str) -> list[QuizSchema]:
    return [
        QuizSchema(
            chapter_id=chapter_id,
            quiz_idx=_quiz_idx(record),
            question=_record_text(record, "question"),
            choices=_record_str_list(record, "choices"),
            answer_idx=_record_int(record, "answer_idx"),
            difficulty=_difficulty(_record_text(record, "difficulty")),
        )
        for record in records
    ]


def _quiz_idx(record: StateRecord) -> int:
    if "quiz_idx" in record:
        return _record_int(record, "quiz_idx")
    return _record_int(record, "slide_idx")


def _voice_schemas(records: StateRecords, chapter_id: str) -> list[VoiceScriptSchema]:
    return [
        VoiceScriptSchema(
            chapter_id=chapter_id,
            slide_idx=_record_int(record, "slide_idx"),
            script_text=_record_text(record, "script_text"),
            audio_url=_optional_record_text(record, "audio_url"),
            duration_hint_sec=_optional_record_number(record, "duration_hint_sec"),
        )
        for record in records
    ]


def _copy_with_chapter(records: StateRecords, chapter_id: str) -> StateRecords:
    return [{"chapter_id": chapter_id, **record} for record in records]


def _merge_voice_audio(voice_scripts: StateRecords, audio_files: StateRecords) -> StateRecords:
    audio_by_slide = {_record_int(record, "slide_idx"): record for record in audio_files}
    rows: StateRecords = []
    for script in voice_scripts:
        slide_idx = _record_int(script, "slide_idx")
        row = dict(script)
        audio = audio_by_slide.get(slide_idx)
        if audio is not None:
            row["audio_url"] = _record_text(audio, "audio_url")
            row["duration_hint_sec"] = _record_number(audio, "duration_hint_sec")
        rows.append(row)
    return rows


def _record_number(record: StateRecord, key: str) -> float:
    value = record.get(key)
    if not isinstance(value, int | float):
        raise ConversionError(f"{key} 숫자가 필요하다.")
    return float(value)


def _optional_record_text(record: StateRecord, key: str) -> str | None:
    if key not in record:
        return None
    return _record_text(record, key)


def _optional_record_number(record: StateRecord, key: str) -> float | None:
    if key not in record:
        return None
    return _record_number(record, key)


def _difficulty(value: str) -> Difficulty:
    if value not in VALID_DIFFICULTY_VALUES:
        raise ConversionError("difficulty 값이 허용 범위를 벗어났다.")
    return cast(Difficulty, value)
