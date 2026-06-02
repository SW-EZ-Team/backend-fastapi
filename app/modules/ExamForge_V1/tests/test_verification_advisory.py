"""검증 응답 파싱 실패 advisory 처리 회귀 테스트."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import route_after_validation
from app.modules.ExamForge_V1.pipeline.nodes.validate_node import validate_node
from app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node import verify_answers_node
from app.modules.ExamForge_V1.pipeline.state import ExamForgeState


class _StubResponse:
    """AI 응답 최소 스텁."""

    def __init__(self, text: str) -> None:
        self.text = text


class _SequenceConnector:
    """호출 순서대로 고정 응답을 반환하는 검증 커넥터."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls = 0

    async def generate(self, req: object) -> _StubResponse:
        index = min(self.calls, len(self.texts) - 1)
        self.calls += 1
        return _StubResponse(self.texts[index])


@pytest.mark.asyncio
async def test_verify_answers_marks_non_json_as_parse_failed_not_failure() -> None:
    """비JSON 검증 응답은 genuine fail이 아니라 parse_failed로 남긴다."""
    connector = _SequenceConnector(["정답은 맞습니다. JSON은 생략합니다."])
    state: ExamForgeState = {
        "answered_questions": [_question("q1", "d1"), _question("q2", "d2")],
        "source_text": "스택은 후입선출 자료구조이다.",
    }

    with patch(
        "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.get_connector",
        return_value=connector,
    ), patch(
        "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.active_verifier_model",
        return_value="stub",
    ), patch(
        "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.verification_concurrency",
        return_value=4,
    ):
        result = await verify_answers_node(state)

    assert connector.calls == 4
    assert result["verification_failures"] == []
    assert result["verification_parse_failed_count"] == 2
    assert result["verification_advisory"] is True
    assert all(q["_verification"]["passed"] is None for q in result["verified_questions"])
    assert all(q["_verification"]["parse_failed"] is True for q in result["verified_questions"])


@pytest.mark.asyncio
async def test_validate_ignores_parse_failed_for_failed_ids_and_accuracy() -> None:
    """parse_failed 문항은 구조 실패나 정확률 실패로 세지 않는다."""
    state: ExamForgeState = {
        "verified_questions": [
            {
                **_question("q1", "d1"),
                "_verification": {
                    "passed": None,
                    "parse_failed": True,
                    "issues": ["검증 응답 파싱 실패"],
                },
            }
        ],
        "exam_plan": {"topic_weights": {"자료구조": 1.0}},
    }

    result = await validate_node(state)

    assert result["failed_question_ids"] == []
    report = result["validation_report"]
    assert report["answer_accuracy_rate"] == 1.0
    assert report["answer_verification_parse_failed_count"] == 1
    assert report["results"][0]["passed"] is True
    assert report["results"][0]["parse_failed"] is True


def test_retry_router_parse_failed_majority_does_not_exhaust() -> None:
    """parse_failed 다수와 genuine fail 0건이면 exhausted로 보내지 않는다."""
    state: ExamForgeState = {
        "verified_questions": [
            {**_question("q1", "d1"), "_verification": {"passed": None, "parse_failed": True}},
            {**_question("q2", "d2"), "_verification": {"passed": None, "parse_failed": True}},
        ],
        "failed_question_ids": ["d1", "d2"],
        "validation_report": {"answer_accuracy_rate": 0.0},
        "retry_count": 3,
        "max_retries": 3,
    }

    assert route_after_validation(state) == "passed"


def _question(question_id: str, draft_id: str) -> dict:
    """검증·구조 테스트에 쓰는 최소 단답형 문항."""
    return {
        "question_id": question_id,
        "draft_id": draft_id,
        "template_id": "ko_short_answer",
        "topic": "자료구조",
        "difficulty": 3,
        "bloom_level": "이해",
        "stem": "스택의 원소 제거 순서를 설명하시오.",
        "correct_answer": "후입선출",
        "explanation": "정답은 후입선출입니다. 마지막에 들어간 원소가 먼저 제거됩니다.",
        "source_reference": "스택은 LIFO 구조이다.",
    }
