from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from app.modules.ChapterStudio_V1.db.weakness_aggregator import aggregate_weak_points


class FakeWeaknessConnection:
    def __init__(self, quiz_rows: Sequence[Mapping[str, object]], exam_rows: Sequence[Mapping[str, object]]) -> None:
        self.quiz_rows = quiz_rows
        self.exam_rows = exam_rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, query: str, *args: object) -> Sequence[Mapping[str, object]]:
        self.calls.append((query, args))
        if "quiz_answer" in query:
            return self.quiz_rows
        return self.exam_rows


@pytest.mark.asyncio
async def test_aggregate_weak_points_summarizes_top_topics() -> None:
    conn = FakeWeaknessConnection(
        quiz_rows=[
            {"key_topics": '["표본분포", "p-value"]', "chapter_name": "추론", "question_text": "", "explanation": ""},
            {"key_topics": "표본분포, 신뢰구간", "chapter_name": "추론", "question_text": "", "explanation": ""},
        ],
        exam_rows=[
            {"analysis": '{"weakTopics":["p-value", {"topic":"신뢰구간"}, "귀무가설"]}'},
        ],
    )

    summary = await aggregate_weak_points(conn, "course-1", "lesson-3")

    assert "표본분포(2회)" in summary
    assert "p-value(2회)" in summary
    assert "신뢰구간(2회)" in summary
    assert conn.calls[0][1] == ("course-1", "lesson-3")
    assert conn.calls[1][1] == ("course-1",)
    assert "lesson_progress" in conn.calls[0][0]
    assert "$1" in conn.calls[0][0] and "$2" in conn.calls[0][0]


@pytest.mark.asyncio
async def test_aggregate_weak_points_parses_camel_and_snake_weak_topics() -> None:
    """mock_exam_submission.analysis의 weakTopics(camelCase)·weak_topics(snake_case)를 모두 읽는다."""
    conn = FakeWeaknessConnection(
        quiz_rows=[],
        exam_rows=[
            {"analysis": '{"weakTopics": ["이차방정식", "판별식"]}'},
            {"analysis": '{"weak_topics": ["판별식", "근의 공식"]}'},
        ],
    )

    summary = await aggregate_weak_points(conn, "course-1", "lesson-2")

    assert "이차방정식" in summary
    assert "판별식(2회)" in summary
    assert "근의 공식" in summary


@pytest.mark.asyncio
async def test_aggregate_weak_points_falls_back_to_plain_text_analysis() -> None:
    """analysis가 JSON이 아닌 평문이어도 토픽 분리로 폴백한다."""
    conn = FakeWeaknessConnection(
        quiz_rows=[],
        exam_rows=[{"analysis": "함수의 극한, 연속성"}],
    )

    summary = await aggregate_weak_points(conn, "course-1", "lesson-2")

    assert "함수의 극한" in summary
    assert "연속성" in summary


@pytest.mark.asyncio
async def test_aggregate_weak_points_returns_empty_without_sources() -> None:
    conn = FakeWeaknessConnection(quiz_rows=[], exam_rows=[])

    summary = await aggregate_weak_points(conn, "course-1", "lesson-1")

    assert summary == ""
