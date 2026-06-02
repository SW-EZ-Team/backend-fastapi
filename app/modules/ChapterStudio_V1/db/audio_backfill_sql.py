from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioUpdatePlan:
    """선택 컬럼에 맞춰 만든 UPDATE 쿼리 계획이다."""

    query: str
    uses_duration: bool


@dataclass(frozen=True)
class AudioBackfillTableColumns:
    """백필 대상 테이블의 컬럼 스냅샷이다."""

    chapter_slide: set[str]
    public_slide: set[str]


def voice_script_sql(schema: str) -> str:
    """lesson_id 기준으로 저장된 슬라이드별 대본을 읽는다."""
    return (
        f"SELECT slide_index AS slide_idx, COALESCE(NULLIF(script_text, ''), text) AS script_text "
        f"FROM {schema}.voice_script WHERE lesson_id = $1 OR chapter_id = $1 ORDER BY slide_index"
    )


def voice_update_sql(schema: str) -> str:
    """voice_script 레코드에 합성된 음성 URL과 길이를 채운다."""
    return (
        f"UPDATE {schema}.voice_script SET audio_url = $3, duration_hint_sec = $4 "
        "WHERE (lesson_id = $1 OR chapter_id = $1) AND slide_index = $2"
    )


def chapter_slide_plan(schema: str, columns: set[str]) -> AudioUpdatePlan | None:
    """chapter_studio.slide 실제 컬럼에 맞춰 음성 동기화 쿼리를 만든다."""
    scope = _scope_clause(columns)
    index_col = _index_column(columns)
    if "audio_url" not in columns or scope is None or index_col is None:
        return None
    duration_col = _duration_column(columns)
    assignments = ["audio_url = $3"]
    if duration_col is not None:
        assignments.append(f"{duration_col} = $4")
    return AudioUpdatePlan(
        query=f"UPDATE {schema}.slide SET {', '.join(assignments)} WHERE {scope} AND {index_col} = $2",
        uses_duration=duration_col is not None,
    )


def public_slide_plan(columns: set[str]) -> AudioUpdatePlan | None:
    """public.slide에 audio 컬럼이 있을 때만 동기화 쿼리를 만든다."""
    if "audio_url" not in columns or "chapter_id" not in columns or "slide_idx" not in columns:
        return None
    duration_col = _duration_column(columns)
    assignments = ["audio_url = $3"]
    if duration_col is not None:
        assignments.append(f"{duration_col} = $4")
    return AudioUpdatePlan(
        query=f"UPDATE public.slide SET {', '.join(assignments)} WHERE chapter_id = $1 AND slide_idx = $2",
        uses_duration=duration_col is not None,
    )


def _scope_clause(columns: set[str]) -> str | None:
    if {"lesson_id", "chapter_id"} <= columns:
        return "(lesson_id = $1 OR chapter_id = $1)"
    if "lesson_id" in columns:
        return "lesson_id = $1"
    return "chapter_id = $1" if "chapter_id" in columns else None


def _index_column(columns: set[str]) -> str | None:
    if "slide_idx" in columns:
        return "slide_idx"
    return "index" if "index" in columns else None


def _duration_column(columns: set[str]) -> str | None:
    if "duration_hint_sec" in columns:
        return "duration_hint_sec"
    return "duration_sec" if "duration_sec" in columns else None


__all__ = [
    "AudioBackfillTableColumns",
    "AudioUpdatePlan",
    "chapter_slide_plan",
    "public_slide_plan",
    "voice_script_sql",
    "voice_update_sql",
]
