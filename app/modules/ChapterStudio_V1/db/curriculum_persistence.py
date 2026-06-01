"""커리큘럼 생성 결과를 DB에 저장한다 (cross-schema, 단일 트랜잭션).

infra 계약: AI 산출물은 chapter_studio 스키마, 강의 메타/진도는 public 스키마.
두 영역은 tutoring_id(=course.id)·lesson_id(=chapter.id) 값으로 연결한다.
따라서 강의 1개마다 public.chapter 1행 + chapter_studio.curriculum_unit 1행을
같은 chapter.id로 연결해 저장한다.
"""
from __future__ import annotations

import json
from typing import Any, Protocol

from app.modules.ChapterStudio_V1.common.ids import new_id


class PersistenceConnection(Protocol):
    def transaction(self) -> Any:
        """asyncpg 트랜잭션 컨텍스트."""

    async def execute(self, query: str, *args: object) -> object:
        """저장 쿼리를 실행한다."""


async def persist_curriculum(
    conn: PersistenceConnection,
    *,
    course: dict[str, Any],
    lessons: list[dict[str, Any]],
    planner_model: str,
) -> int:
    """커리큘럼(plan + N개 강의)을 저장하고 course 상태를 CURRICULUM_READY로 전이한다.

    같은 course에 대한 재요청은 멱등하게 처리한다(기존 plan/chapter 제거 후 재삽입).
    반환값은 저장된 강의 수다.
    """
    course_id = course["id"]
    plan_id = new_id("cur")

    async with conn.transaction():
        # 멱등성: 기존 커리큘럼/강의를 먼저 제거한다 (재생성 대비)
        await conn.execute(
            "DELETE FROM chapter_studio.curriculum_unit "
            "WHERE curriculum_plan_id IN "
            "(SELECT id FROM chapter_studio.curriculum_plan WHERE tutoring_id = $1)",
            course_id,
        )
        await conn.execute(
            "DELETE FROM chapter_studio.curriculum_plan WHERE tutoring_id = $1",
            course_id,
        )
        await conn.execute("DELETE FROM public.chapter WHERE course_id = $1", course_id)

        # 커리큘럼 plan (chapter_studio)
        await conn.execute(
            "INSERT INTO chapter_studio.curriculum_plan "
            "(id, tutoring_id, user_id, title, source_type, source_ref, status, planner_model) "
            "VALUES ($1, $2, $3, $4, $5, $6, 'draft', $7)",
            plan_id,
            course_id,
            course["user_id"],
            course.get("course_name") or "AI 과외",
            course.get("source_type") or "topic",
            course.get("source_pdf_url"),
            planner_model,
        )

        # 강의 N개 — public.chapter + chapter_studio.curriculum_unit 를 같은 chapter.id로 연결
        for lesson in lessons:
            chapter_id = new_id("chp")  # ^chp_[0-9A-Z]{26}$
            order_index = int(lesson["order"])
            title = str(lesson["title"])[:200]
            description = lesson.get("description") or ""
            slide_count = int(lesson.get("slide_count") or 0)
            estimated_minutes = int(lesson.get("estimated_minutes") or 0)
            learning_goal = lesson.get("learning_goal")
            key_topics = json.dumps(lesson.get("key_topics") or [], ensure_ascii=False)

            # Spring 조회 대상 — 강의 메타(진도/잠금)
            await conn.execute(
                "INSERT INTO public.chapter "
                "(id, course_id, chapter_name, description, order_index, total_slides, "
                " completed_slides, estimated_minutes, key_topics, status, xp_earned) "
                "VALUES ($1, $2, $3, $4, $5, $6, 0, $7, $8, 'LOCKED', 0)",
                chapter_id,
                course_id,
                title,
                description,
                order_index,
                slide_count,
                estimated_minutes,
                key_topics,
            )
            # FastAPI 강의생성이 읽는 커리큘럼 초안 (lesson_id = 위 chapter.id)
            await conn.execute(
                "INSERT INTO chapter_studio.curriculum_unit "
                "(id, curriculum_plan_id, lesson_id, order_index, title, summary, "
                " learning_goal, slide_count, estimated_minutes, status) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'draft')",
                new_id("cun"),
                plan_id,
                chapter_id,
                order_index,
                title,
                description,
                learning_goal,
                slide_count,
                estimated_minutes,
            )

        # course 상태 전이 — Spring confirmCurriculum이 CURRICULUM_READY에서만 ACTIVE 전환 가능
        await conn.execute(
            "UPDATE public.course "
            "SET status = 'CURRICULUM_READY', total_chapters = $2, updated_at = NOW() "
            "WHERE id = $1",
            course_id,
            len(lessons),
        )

    return len(lessons)
