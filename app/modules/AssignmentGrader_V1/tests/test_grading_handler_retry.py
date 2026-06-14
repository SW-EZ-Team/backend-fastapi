# AssignmentGrader_V1 채점 핸들러 단위 테스트다.
# Spring 콜백 재시도(지수 백오프 3회)와 실패 콜백 경로를 검증한다.
from __future__ import annotations

import pytest

from app.modules.AssignmentGrader_V1 import grading_handler
from app.modules.AssignmentGrader_V1.grading_handler import handle_text_grading_request
from app.modules.AssignmentGrader_V1.schemas import GradeRequest
from app.modules.AssignmentGrader_V1.spring_callback import SpringCallbackError
from app.modules.AssignmentGrader_V1.text_grader import TextGradingError, TextGradingResult


def _request() -> GradeRequest:
    return GradeRequest(
        submission_id="sbm_TEST00000000000000000001",
        assignment_title="이차방정식 풀이 과제",
        assignment_description="근의 공식을 적용해 푼다.",
        assignment_questions=["x^2-4x+3=0의 해를 구하시오."],
        answer_text="x=1, x=3 입니다.",
    )


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """백오프 대기를 제거해 테스트를 즉시 실행한다."""

    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(grading_handler.asyncio, "sleep", fake_sleep)


@pytest.mark.anyio
async def test_done_callback_retries_until_success(monkeypatch: pytest.MonkeyPatch, no_sleep: None) -> None:
    """done 콜백이 일시 실패 후 재시도로 성공한다(총 3회 한도)."""
    attempts: list[str] = []

    def fake_grade(*args: object, **kwargs: object) -> TextGradingResult:
        return TextGradingResult(score=85, feedback="구체 피드백", ai_confidence=0.9)

    def fake_callback(submission_id: str, score: int, feedback: str, ai_confidence: float, status_transition: str = "done") -> None:
        attempts.append(status_transition)
        if len(attempts) < 3:
            raise SpringCallbackError("Spring 일시 오류")

    monkeypatch.setattr(grading_handler, "grade_text_submission", fake_grade)
    monkeypatch.setattr(grading_handler, "send_ai_result_callback", fake_callback)

    await handle_text_grading_request(_request())

    assert attempts == ["done", "done", "done"]


@pytest.mark.anyio
async def test_grading_failure_sends_failed_callback(monkeypatch: pytest.MonkeyPatch, no_sleep: None) -> None:
    """채점 실패 시 failed 콜백을 전송해 submission이 영구 queued로 남지 않는다."""
    captured: dict[str, object] = {}

    def fake_grade(*args: object, **kwargs: object) -> TextGradingResult:
        raise TextGradingError("Gemini 호출 실패")

    def fake_callback(submission_id: str, score: int, feedback: str, ai_confidence: float, status_transition: str = "done") -> None:
        captured["submission_id"] = submission_id
        captured["score"] = score
        captured["status"] = status_transition

    monkeypatch.setattr(grading_handler, "grade_text_submission", fake_grade)
    monkeypatch.setattr(grading_handler, "send_ai_result_callback", fake_callback)

    await handle_text_grading_request(_request())

    assert captured["status"] == "failed"
    assert captured["score"] == 0


@pytest.mark.anyio
async def test_callback_gives_up_after_three_attempts(monkeypatch: pytest.MonkeyPatch, no_sleep: None) -> None:
    """3회 모두 실패하면 더 재시도하지 않고 False로 종료한다(무한 재시도 금지)."""
    attempts = {"count": 0}

    def fake_callback(*args: object, **kwargs: object) -> None:
        attempts["count"] += 1
        raise SpringCallbackError("Spring 다운")

    monkeypatch.setattr(grading_handler, "send_ai_result_callback", fake_callback)

    ok = await grading_handler._send_callback_with_retry(
        "sbm_TEST00000000000000000001",
        score=70,
        feedback="피드백",
        ai_confidence=0.8,
        status_transition="done",
    )

    assert ok is False
    assert attempts["count"] == 3
