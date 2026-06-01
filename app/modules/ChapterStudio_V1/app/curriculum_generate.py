"""커리큘럼 생성 오케스트레이션.

Spring POST /api/curriculum/generate 수신 후 백그라운드에서 실행된다.
흐름: public.course 조회 → planner(MLX/Opus 등 ACTIVE_PLANNER_MODEL) 생성 →
JSON 파싱 → cross-schema 저장(persist_curriculum).
DB 쓰기는 schema-qualified 명시(get_connection은 search_path 미설정).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from app.modules.ChapterStudio_V1.ai_connectors.registry import get_planner_connector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.common.config import active_planner_model
from app.modules.ChapterStudio_V1.db.curriculum_persistence import persist_curriculum
from common.db import get_connection

_LOG = logging.getLogger(__name__)

_PLANNER_SYSTEM = (
    "너는 한국어 AI 과외 커리큘럼 설계자다. 주어진 주제로 점진적으로 심화하는 강의 목차를 "
    "설계한다. 반드시 JSON 배열만 출력하고, 설명·코드펜스·생각과정은 절대 출력하지 않는다."
)

# <think>...</think> 추론 블록 제거용 (Qwen3 thinking 출력 대비)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_SPRING_COMMIT_RETRY_ATTEMPTS = 5
_SPRING_COMMIT_RETRY_DELAY_SEC = 1.0
_COURSE_FAILED_STATUS = "CURRICULUM_FAILED"


async def generate_and_store_curriculum(
    course_id: str,
    subject: str,
    lesson_count: int,
    source_type: str,
) -> None:
    """커리큘럼을 생성·저장하고 실패 시 course 상태를 실패로 전이한다."""
    try:
        course = await _load_course_after_spring_commit(course_id)
        if course is None:
            _LOG.error("[curriculum] course 없음 — courseId=%s", course_id)
            await mark_course_curriculum_failed(course_id, "course not found")
            return

        lessons = await _plan_lessons(course, subject, max(1, lesson_count))
        if not lessons:
            _LOG.error("[curriculum] planner가 유효한 강의를 만들지 못함 — courseId=%s", course_id)
            await mark_course_curriculum_failed(course_id, "planner returned empty lessons")
            return

        async with get_connection() as conn:
            saved = await persist_curriculum(
                conn, course=course, lessons=lessons, planner_model=active_planner_model()
            )
        _LOG.info("[curriculum] 저장 완료 — courseId=%s, 강의 %d개", course_id, saved)
    except Exception as exc:
        _LOG.error("[curriculum] 생성 실패 — courseId=%s, error=%s", course_id, exc, exc_info=True)
        await mark_course_curriculum_failed(course_id, str(exc))


async def mark_course_curriculum_failed(course_id: str, reason: str) -> None:
    """침묵 실패를 막기 위해 public.course 상태를 실패로 전이한다."""
    try:
        async with get_connection() as conn:
            await conn.execute(
                "UPDATE public.course SET status = $2, updated_at = NOW() WHERE id = $1",
                course_id,
                _COURSE_FAILED_STATUS,
            )
    except Exception as exc:
        _LOG.error(
            "[curriculum] 실패 상태 기록 실패 — courseId=%s, reason=%s, error=%s",
            course_id,
            reason,
            exc,
        )


async def _load_course_after_spring_commit(course_id: str) -> dict | None:
    """Spring course INSERT 커밋 직후 호출되는 경우를 위해 짧게 재조회한다."""
    for attempt in range(1, _SPRING_COMMIT_RETRY_ATTEMPTS + 1):
        course = await _load_course(course_id)
        if course is not None:
            return course
        if attempt < _SPRING_COMMIT_RETRY_ATTEMPTS:
            _LOG.info(
                "[curriculum] course 커밋 대기 — courseId=%s, retry=%d/%d",
                course_id,
                attempt,
                _SPRING_COMMIT_RETRY_ATTEMPTS,
            )
            await asyncio.sleep(_SPRING_COMMIT_RETRY_DELAY_SEC)
    return None


async def _load_course(course_id: str) -> dict | None:
    """public.course에서 커리큘럼 생성에 필요한 메타를 읽는다."""
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, course_name, subject, source_type, source_pdf_url, topic_text "
            "FROM public.course WHERE id = $1",
            course_id,
        )
    return dict(row) if row is not None else None


async def _plan_lessons(course: dict, subject: str, lesson_count: int) -> list[dict]:
    """ACTIVE_PLANNER_MODEL 커넥터로 강의 목차를 생성하고 파싱한다."""
    topic = course.get("topic_text") or course.get("course_name") or subject or "학습 주제"
    subject_name = course.get("subject") or subject or "일반"
    connector = get_planner_connector()
    req = ChapterAIRequest(
        system=_PLANNER_SYSTEM,
        user=_build_prompt(topic, subject_name, lesson_count),
        max_tokens=6000,
        temperature=0.3,
    )
    resp = await connector.generate(req)
    return _parse_lessons(resp.text, lesson_count)


def _build_prompt(topic: str, subject: str, n: int) -> str:
    """planner에게 정확히 n개의 강의를 JSON 배열로 요청한다."""
    return (
        "/no_think\n"
        f"다음 과외의 강의 목차를 정확히 {n}개 설계하라.\n"
        f"주제: {topic}\n과목: {subject}\n"
        "각 강의는 이전 강의를 기반으로 점진적으로 심화한다.\n\n"
        "아래 JSON 배열만 출력하라 (다른 텍스트·코드펜스 금지):\n"
        '[{"order":1,"title":"강의 제목","description":"한 문장 요약",'
        '"slide_count":12,"estimated_minutes":30,"learning_goal":"학습 목표",'
        '"key_topics":["키워드1","키워드2","키워드3"]}]\n'
        f"규칙: order는 1부터 {n}까지 연속. slide_count 10~15, estimated_minutes 20~60, "
        "key_topics 3~5개. 모든 텍스트는 한국어."
    )


def _parse_lessons(raw: str, n: int) -> list[dict]:
    """모델 출력에서 JSON 배열을 추출·정규화한다. 실패 시 빈 리스트."""
    text = _THINK_RE.sub("", raw).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        _LOG.error("[curriculum] JSON 배열을 찾지 못함: %r", text[:300])
        return []
    try:
        items = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        _LOG.error("[curriculum] JSON 파싱 실패: %s | %r", exc, text[start : start + 300])
        return []
    if not isinstance(items, list):
        return []

    lessons: list[dict] = []
    for idx, item in enumerate(items[:n], start=1):
        if not isinstance(item, dict) or not item.get("title"):
            continue
        topics = item.get("key_topics")
        lessons.append(
            {
                "order": idx,
                "title": str(item["title"]).strip(),
                "description": str(item.get("description") or "").strip(),
                "slide_count": _clamp_int(item.get("slide_count"), 12, 1, 30),
                "estimated_minutes": _clamp_int(item.get("estimated_minutes"), 30, 1, 600),
                "learning_goal": (str(item["learning_goal"]).strip() if item.get("learning_goal") else None),
                "key_topics": [str(t).strip() for t in topics][:6] if isinstance(topics, list) else [],
            }
        )
    return lessons


def _clamp_int(value: object, default: int, low: int, high: int) -> int:
    """정수로 변환하고 [low, high] 범위로 제한한다."""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(low, min(high, n))
