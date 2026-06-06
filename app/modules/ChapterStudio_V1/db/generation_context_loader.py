"""강의 생성 컨텍스트 DB 조회·저장 모듈 — ChapterStudio 파이프라인 진입점.

load_generation_context: lesson_id → GenerationContext (DB 읽기)
save_reference_book_context: lesson_id × ReferenceBookContext → DB upsert (쓰기)

변환 로직은 _converters.py에 위임해 단일 책임 원칙을 유지한다.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext
from app.modules.ChapterStudio_V1.common.config import database_schema
from app.modules.ChapterStudio_V1.common.errors import StorageError
from app.modules.ChapterStudio_V1.db._converters import (
    bool_field,
    context_mapping,
    depth_field,
    int_field,
    reference_context_field,
    source_mode_field,
    table_ref,
    teacher_field,
    text_field,
)
from app.modules.ChapterStudio_V1.db.persistence_sql import save_reference_book_context_sql


class GenerationContextConnection(Protocol):
    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None:
        """asyncpg connection과 테스트 대역의 최소 조회 인터페이스다."""


class SaveReferenceBookConnection(Protocol):
    async def execute(self, query: str, *args: object) -> str:
        """OCR 컨텍스트 upsert를 위한 최소 쓰기 인터페이스다."""


async def save_reference_book_context(
    conn: SaveReferenceBookConnection,
    lesson_id: str,
    context: ReferenceBookContext,
) -> None:
    """OCR 완료된 참고도서 컨텍스트를 lesson_generation_status에 upsert한다.

    generation_context JSONB의 reference_book_context 키만 병합하므로
    기존의 depth, tone 등 다른 설정값은 그대로 유지된다.
    """
    payload = json.dumps({"reference_book_context": context.model_dump()})
    await conn.execute(
        save_reference_book_context_sql(database_schema()),
        lesson_id,
        payload,
    )


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
FROM {table_ref(schema, 'curriculum_unit')} cu
JOIN {table_ref(schema, 'curriculum_plan')} cp ON cp.id = cu.curriculum_plan_id
LEFT JOIN public.course co ON co.id = cp.tutoring_id
LEFT JOIN {table_ref(schema, 'lesson_generation_status')} lgs ON lgs.lesson_id = cu.lesson_id
WHERE cu.lesson_id = $1
"""


def row_to_generation_context(row: Mapping[str, object]) -> GenerationContext:
    """DB row와 JSONB 스냅샷을 단일 생성 컨텍스트로 병합한다."""
    ctx = context_mapping(row.get("generation_context"))
    return GenerationContext(
        lesson_id=text_field(row, "lesson_id", ""),
        tutoring_id=text_field(row, "tutoring_id", ""),
        user_id=text_field(row, "user_id", ""),
        curriculum_plan_id=text_field(row, "curriculum_plan_id", ""),
        topic=text_field(row, "topic", "제목 없는 강의"),
        source_mode=source_mode_field(row.get("source_mode")),
        pdf_file_name=text_field(row, "pdf_file_name", ""),
        duration_days=int_field(ctx, "duration_days", 30),
        depth=depth_field(ctx.get("depth")),
        teacher=teacher_field(ctx.get("teacher")),
        tone=int_field(ctx, "tone", 50),
        pace=int_field(ctx, "pace", 50),
        tutor_depth=int_field(ctx, "tutor_depth", 50),
        socratic=int_field(ctx, "socratic", 70),
        use_formal_speech=bool_field(ctx, "use_formal_speech", True),
        use_emoji=bool_field(ctx, "use_emoji", False),
        tutor_name=text_field(ctx, "tutor_name", ""),
        tutor_tagline=text_field(ctx, "tutor_tagline", ""),
        is_default_tutor=bool_field(ctx, "is_default_tutor", True),
        tutor_id=text_field(row, "tutor_id", text_field(ctx, "tutor_id", "")),
        voice_sample_url=text_field(ctx, "voice_sample_url", ""),
        audience_level=text_field(ctx, "audience_level", "일반 학습자"),
        learning_goal=text_field(row, "learning_goal", text_field(ctx, "learning_goal", "핵심 개념 이해와 실습")),
        weak_points=text_field(ctx, "weak_points", ""),
        chapter_title=text_field(row, "chapter_title", "데모 챕터"),
        chapter_brief=text_field(row, "chapter_brief", ""),
        template=text_field(row, "template", text_field(ctx, "template", "auto")),
        slide_count=int_field(row, "slide_count", int_field(ctx, "slide_count", 12)),
        reference_book_context=reference_context_field(ctx.get("reference_book_context")),
    )


GENERATION_CONTEXT_SQL = generation_context_sql("chapter_studio")
