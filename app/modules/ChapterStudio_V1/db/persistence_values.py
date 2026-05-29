from __future__ import annotations

import json
from typing import cast

from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState, StateRecord, StateRecords


def records(state: ChapterStudioState, key: str) -> StateRecords:
    value = state.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ConversionError(f"{key} 목록이 필요하다.")
    return cast(StateRecords, value)


def optional_records(state: ChapterStudioState, key: str) -> StateRecords:
    if key not in state:
        return []
    return records(state, key)


def voice_rows(state: ChapterStudioState) -> StateRecords:
    audio_by_slide = {record_int(row, "slide_idx"): row for row in optional_records(state, "voice_audio_files")}
    rows: StateRecords = []
    for script in records(state, "voice_scripts"):
        row = dict(script)
        audio = audio_by_slide.get(record_int(script, "slide_idx"))
        if audio is not None:
            row["audio_url"] = record_text(audio, "audio_url")
            duration = optional_number(audio, "duration_hint_sec")
            if duration is not None:
                row["duration_hint_sec"] = duration
        rows.append(row)
    return rows


def state_record(state: ChapterStudioState, key: str) -> StateRecord:
    value = state.get(key)
    return cast(StateRecord, value) if isinstance(value, dict) else {}


def state_text(state: ChapterStudioState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or value == "":
        raise ConversionError(f"{key} 문자열이 필요하다.")
    return value


def record_text(row: StateRecord, key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or value == "":
        raise ConversionError(f"{key} 문자열이 필요하다.")
    return value


def optional_text(row: StateRecord, key: str) -> str | None:
    value = row.get(key)
    return value if isinstance(value, str) and value else None


def record_int(row: StateRecord, key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int):
        raise ConversionError(f"{key} 정수가 필요하다.")
    return value


def optional_number(row: StateRecord, key: str) -> float | None:
    value = row.get(key)
    return float(value) if isinstance(value, int | float) else None


def record_str_list(row: StateRecord, key: str) -> list[str]:
    value = row.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConversionError(f"{key} 문자열 목록이 필요하다.")
    return cast(list[str], value)


def record_default_text(row: StateRecord, key: str, default: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) and value != "" else default


def record_default_int(row: StateRecord, key: str, default: int) -> int:
    value = row.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def record_default_str_list(row: StateRecord, key: str) -> list[str]:
    value = row.get(key)
    return cast(list[str], value) if isinstance(value, list) and all(isinstance(item, str) for item in value) else []


def summary(state: ChapterStudioState) -> dict[str, int]:
    return {key: len(records(state, key)) for key in ("slides", "quiz_set", "voice_scripts")}


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def id_for(chapter_id: str, kind: str, idx: int) -> str:
    return f"{chapter_id}:{kind}:{idx}"


def first_line(value: str) -> str:
    return value.splitlines()[0][:255] if value.splitlines() else "과제"
