from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from pydantic import ValidationError

from app.modules.ChapterStudio_V1.app.frontend_contract import DepthLevel, SourceMode, TeacherId
from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext
from app.modules.ChapterStudio_V1.common.config import database_schema
from app.modules.ChapterStudio_V1.common.errors import ConversionError, StorageError


class GenerationContextConnection(Protocol):
    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None:
        """asyncpg connection과 테스트 대역의 최소 조회 인터페이스다."""


async def load_generation_context(conn: GenerationContextConnection, lesson_id: str) -> GenerationContext:
    """lesson_id 기준으로 ChapterStudio 생성 입력을 DB에서 읽는다."""
    row = await conn.fetchrow(generation_context_sql(database_schema()), lesson_id)
    if row is None:
        raise StorageError(f"강의 생성 입력을 찾을 수 없다: {lesson_id}")
    return row_to_generation_context(row)


def generation_context_sql(schema: str) -> str:
    """schema 설정을 반영한 생성 입력 조회 SQL을 만든다."""
    return f"""
SELECT
    cu.lesson_id,
    cp.tutoring_id,
    cp.user_id,
    cp.id AS curriculum_plan_id,
    COALESCE(NULLIF(cu.title, ''), cp.title) AS topic,
    cp.source_type AS source_mode,
    cp.source_ref AS pdf_file_name,
    cu.title AS chapter_title,
    cu.summary AS chapter_brief,
    cu.learning_goal,
    COALESCE(lgs.requested_slide_count, cu.slide_count) AS slide_count,
    COALESCE(lgs.requested_template, 'auto') AS template,
    COALESCE(co.tutor_id, '') AS tutor_id,
    COALESCE(lgs.generation_context, '{{}}'::jsonb) AS generation_context
FROM {_table(schema, 'curriculum_unit')} cu
JOIN {_table(schema, 'curriculum_plan')} cp ON cp.id = cu.curriculum_plan_id
LEFT JOIN public.course co ON co.id = cp.tutoring_id
LEFT JOIN {_table(schema, 'lesson_generation_status')} lgs ON lgs.lesson_id = cu.lesson_id
WHERE cu.lesson_id = $1
"""


def row_to_generation_context(row: Mapping[str, object]) -> GenerationContext:
    """DB row와 JSONB 스냅샷을 단일 생성 컨텍스트로 병합한다."""
    context = _context(row.get("generation_context"))
    return GenerationContext(
        lesson_id=_text(row, "lesson_id", ""),
        tutoring_id=_text(row, "tutoring_id", ""),
        user_id=_text(row, "user_id", ""),
        curriculum_plan_id=_text(row, "curriculum_plan_id", ""),
        topic=_text(row, "topic", "제목 없는 강의"),
        source_mode=_source_mode(row.get("source_mode")),
        pdf_file_name=_text(row, "pdf_file_name", ""),
        duration_days=_int(context, "duration_days", 30),
        depth=_depth(context.get("depth")),
        teacher=_teacher(context.get("teacher")),
        tone=_int(context, "tone", 50),
        pace=_int(context, "pace", 50),
        tutor_depth=_int(context, "tutor_depth", 50),
        socratic=_int(context, "socratic", 70),
        use_formal_speech=_bool(context, "use_formal_speech", True),
        use_emoji=_bool(context, "use_emoji", False),
        tutor_name=_text(context, "tutor_name", ""),
        tutor_tagline=_text(context, "tutor_tagline", ""),
        is_default_tutor=_bool(context, "is_default_tutor", True),
        tutor_id=_text(row, "tutor_id", _text(context, "tutor_id", "")),
        voice_sample_url=_text(context, "voice_sample_url", ""),
        audience_level=_text(context, "audience_level", "일반 학습자"),
        learning_goal=_text(row, "learning_goal", _text(context, "learning_goal", "핵심 개념 이해와 실습")),
        weak_points=_text(context, "weak_points", ""),
        chapter_title=_text(row, "chapter_title", "데모 챕터"),
        chapter_brief=_text(row, "chapter_brief", ""),
        template=_text(row, "template", _text(context, "template", "auto")),
        slide_count=_int(row, "slide_count", _int(context, "slide_count", 12)),
        reference_book_context=_reference_context(context.get("reference_book_context")),
    )


def _context(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}


def _text(source: Mapping[str, object], key: str, default: str) -> str:
    value = source.get(key)
    if isinstance(value, str) and value != "":
        return value
    return default


def _int(source: Mapping[str, object], key: str, default: int) -> int:
    value = source.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _bool(source: Mapping[str, object], key: str, default: bool) -> bool:
    value = source.get(key)
    if isinstance(value, bool):
        return value
    return default


def _source_mode(value: object) -> SourceMode:
    if value in ("topic", "pdf"):
        return cast(SourceMode, value)
    raise ConversionError("source_type은 topic 또는 pdf여야 한다.")


def _depth(value: object) -> DepthLevel:
    if value is None or value == "":
        return "normal"
    if value in ("basic", "normal", "deep"):
        return cast(DepthLevel, value)
    raise ConversionError("depth는 basic, normal, deep 중 하나여야 한다.")


def _teacher(value: object) -> TeacherId:
    if value is None or value == "":
        return "owl"
    if value in ("owl", "cat", "fox", "bear"):
        return cast(TeacherId, value)
    raise ConversionError("teacher는 owl, cat, fox, bear 중 하나여야 한다.")


def _reference_context(value: object) -> ReferenceBookContext | None:
    if not isinstance(value, Mapping):
        return None
    try:
        context = ReferenceBookContext.model_validate(value)
    except ValidationError as exc:
        raise ConversionError(f"reference_book_context 형식 오류: {exc}") from exc
    if not context.has_hits():
        return None
    return context


def _table(schema: str, name: str) -> str:
    return f"{schema}.{name}"


GENERATION_CONTEXT_SQL = generation_context_sql("chapter_studio")
