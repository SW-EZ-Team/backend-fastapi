from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Protocol

_MAX_TOPICS = 5


class WeaknessConnection(Protocol):
    async def fetch(self, query: str, *args: object) -> Sequence[Mapping[str, object]]:
        """asyncpg connection과 테스트 대역이 공유하는 최소 조회 인터페이스다."""


async def aggregate_weak_points(conn: WeaknessConnection, course_id: str, lesson_id: str) -> str:
    """대상 강의 이전 완료 강의와 모의고사 분석에서 상위 약점을 요약한다."""
    topics: list[str] = []
    for row in await conn.fetch(_QUIZ_WEAKNESS_SQL, course_id, lesson_id):
        topics.extend(_quiz_topics(row))
    for row in await conn.fetch(_MOCK_EXAM_SQL, course_id):
        topics.extend(_analysis_topics(_row_value(row, "analysis")))
    return _summarize(topics)


def _quiz_topics(row: Mapping[str, object]) -> list[str]:
    topics = _topics_from_value(_row_value(row, "key_topics"))
    if topics:
        return topics
    fallback = _row_value(row, "chapter_name") or _row_value(row, "question_text") or _row_value(row, "explanation")
    return _topics_from_value(fallback)


def _analysis_topics(value: object) -> list[str]:
    if not isinstance(value, str) or value.strip() == "":
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return _topics_from_value(value)
    if isinstance(parsed, Mapping):
        weak_topics = parsed.get("weakTopics") or parsed.get("weak_topics")
        return _topics_from_value(weak_topics)
    return _topics_from_value(parsed)


def _topics_from_value(value: object) -> list[str]:
    if isinstance(value, str):
        return _topics_from_text_or_json(value)
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return _topics_from_sequence(value)
    if isinstance(value, Mapping):
        return _topics_from_mapping(value)
    return []


def _topics_from_text_or_json(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _split_topics(text)
    return _topics_from_value(parsed)


def _topics_from_sequence(items: Sequence[object]) -> list[str]:
    topics: list[str] = []
    for item in items:
        topics.extend(_topics_from_value(item))
    return topics


def _topics_from_mapping(value: Mapping[object, object]) -> list[str]:
    for key in ("topic", "name", "label", "concept"):
        item = value.get(key)
        if isinstance(item, str):
            return _split_topics(item)
    return []


def _split_topics(text: str) -> list[str]:
    raw_items = re.split(r"[,;/\n]|·", text)
    return [topic for item in raw_items if (topic := _normalize_topic(item))]


def _normalize_topic(value: str) -> str:
    topic = re.sub(r"^[\s\-*•0-9.)]+", "", value).strip()
    topic = re.sub(r"\s+", " ", topic)
    if not topic or len(topic) > 80:
        return ""
    return topic[:60]


def _summarize(topics: list[str]) -> str:
    counter = Counter(topics)
    if not counter:
        return ""
    parts = [_format_topic(topic, count) for topic, count in counter.most_common(_MAX_TOPICS)]
    return ", ".join(parts)


def _format_topic(topic: str, count: int) -> str:
    if count <= 1:
        return topic
    return f"{topic}({count}회)"


def _row_value(row: Mapping[str, object], key: str) -> object:
    try:
        return row[key]
    except KeyError:
        return None


_QUIZ_WEAKNESS_SQL = """
WITH target AS (
    SELECT id, course_id, order_index
    FROM public.chapter
    WHERE course_id = $1 AND id = $2
),
completed AS (
    SELECT c.id, c.chapter_name, c.key_topics, lp.user_id
    FROM public.chapter c
    JOIN target t ON t.course_id = c.course_id AND c.order_index < t.order_index
    JOIN public.course co ON co.id = t.course_id
    JOIN public.lesson_progress lp ON lp.chapter_id = c.id AND lp.user_id = co.user_id
    WHERE lp.is_completed = TRUE
)
SELECT completed.key_topics, completed.chapter_name, q.question_text, q.explanation
FROM completed
JOIN public.quiz q ON q.chapter_id = completed.id
JOIN public.quiz_answer qa ON qa.quiz_id = q.id AND qa.user_id = completed.user_id
WHERE qa.is_correct = FALSE
"""

_MOCK_EXAM_SQL = """
SELECT ms.analysis
FROM public.mock_exam_submission ms
JOIN public.mock_exam me ON me.id = ms.mock_exam_id
JOIN public.course c ON c.id = me.course_id AND c.user_id = ms.user_id
WHERE me.course_id = $1
  AND ms.analysis IS NOT NULL
  AND ms.analysis <> ''
ORDER BY ms.submitted_at DESC
"""


__all__ = ["aggregate_weak_points"]
