"""모의고사 생성 결과를 public 스키마에 저장한다 (Spring 폴링 대상).

infra 계약: Spring MockExamService는 public.mock_exam(상태/총점)과
public.mock_exam_question(문항)을 조회한다. 어댑터는 ExamForge 생성 결과를
이 두 테이블에 직접 INSERT/UPDATE 해야 Spring이 GENERATING→READY 전이를 보고
getExamDetail로 문항을 읽을 수 있다(커리큘럼 어댑터가 public.chapter에 쓴 패턴과 동일).

생성 입력(source_text)은 Spring이 보내지 않으므로 course + 그 course의 chapter
(+ slide 본문)에서 학습 자료를 조립한다.
"""
from __future__ import annotations

from typing import Any, Protocol

from app.modules.ExamForge_V1.common.ids import new_id
from app.modules.ExamForge_V1.db.mockexam_mapping import to_question_rows


class PersistenceConnection(Protocol):
    def transaction(self) -> Any:
        """asyncpg 트랜잭션 컨텍스트."""

    async def execute(self, query: str, *args: object) -> object:
        """저장 쿼리를 실행한다."""

    async def fetchrow(self, query: str, *args: object) -> Any:
        """단일 행을 조회한다."""

    async def fetch(self, query: str, *args: object) -> Any:
        """여러 행을 조회한다."""


async def load_exam_context(conn: PersistenceConnection, exam_id: str) -> dict[str, Any] | None:
    """mock_exam 행 + 소속 course 메타를 읽는다. 없으면 None."""
    row = await conn.fetchrow(
        "SELECT m.id AS exam_id, m.course_id, m.exam_type, m.question_count, "
        "       m.difficulty, m.time_limit, "
        "       c.course_name, c.subject, c.topic_text "
        "FROM public.mock_exam m "
        "JOIN public.course c ON c.id = m.course_id "
        "WHERE m.id = $1",
        exam_id,
    )
    return dict(row) if row is not None else None


async def build_source_text(conn: PersistenceConnection, course_id: str, topic_text: str | None) -> str:
    """course의 chapter(+slide 본문)에서 출제용 학습 자료 텍스트를 조립한다.

    chapter 메타(제목/설명/핵심주제)와 slide 본문을 이어 붙인다. 슬라이드 본문이
    아직 없으면 chapter 메타만으로 구성한다. 최후 폴백은 course.topic_text.
    """
    chapters = await conn.fetch(
        "SELECT id, chapter_name, description, key_topics "
        "FROM public.chapter WHERE course_id = $1 ORDER BY order_index ASC",
        course_id,
    )
    parts: list[str] = []
    for ch in chapters:
        parts.append(f"## {ch['chapter_name']}")
        if ch["description"]:
            parts.append(str(ch["description"]))
        if ch["key_topics"]:
            parts.append(f"핵심 주제: {ch['key_topics']}")
        slides = await conn.fetch(
            "SELECT title, content FROM public.slide "
            "WHERE chapter_id = $1 ORDER BY slide_idx ASC",
            ch["id"],
        )
        for sl in slides:
            if sl["title"]:
                parts.append(str(sl["title"]))
            if sl["content"]:
                parts.append(str(sl["content"]))

    assembled = "\n".join(p for p in parts if p).strip()
    return assembled or (topic_text or "").strip()


async def persist_exam_result(
    conn: PersistenceConnection,
    *,
    exam_id: str,
    questions: list[dict[str, Any]],
) -> int:
    """문항을 저장하고 mock_exam 상태를 READY로 전이한다(단일 트랜잭션).

    재요청 멱등성을 위해 기존 문항을 먼저 제거한다. 반환값은 저장된 문항 수다.
    문항이 0개면 상태를 전이하지 않고 0을 반환한다(호출부가 실패로 처리).
    """
    rows = to_question_rows(questions)
    if not rows:
        return 0

    total_points = sum(int(r["points"]) for r in rows)

    async with conn.transaction():
        # 멱등성: 같은 모의고사의 기존 문항 제거 후 재삽입
        await conn.execute(
            "DELETE FROM public.mock_exam_question WHERE mock_exam_id = $1", exam_id
        )

        for row in rows:
            await conn.execute(
                "INSERT INTO public.mock_exam_question "
                "(id, mock_exam_id, question_idx, question_text, question_type, "
                " options, correct_option, explanation, points) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                new_id("mq"),  # ^mq_[0-9A-Z]{26}$
                exam_id,
                row["question_idx"],
                row["question_text"],
                row["question_type"],
                row["options"],
                row["correct_option"],
                row["explanation"],
                row["points"],
            )

        # Spring getExamDetail/submitExam은 READY 상태에서만 동작한다
        await conn.execute(
            "UPDATE public.mock_exam "
            "SET status = 'READY', total_points = $2 "
            "WHERE id = $1",
            exam_id,
            total_points,
        )

    return len(rows)
