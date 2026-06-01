"""Spring mock-exam 어댑터 커밋 레이스 회귀 테스트."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import pytest

import app.modules.ExamForge_V1 as examforge_module
from app.modules.ExamForge_V1.app import spring_adapter
from app.modules.ExamForge_V1.schemas.request import ExamForgeRequest


class FakeConnectionManager:
    """DB 연결 컨텍스트를 대체하는 최소 async manager."""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakeQuestion:
    """생성 결과 문항의 model_dump 호출만 검증한다."""

    def model_dump(self) -> dict[str, object]:
        return {"question_id": "q1", "stem": "테스트 문항"}


class FakeResponse:
    """ExamForge 응답의 questions 속성만 제공한다."""

    questions: list[FakeQuestion]

    def __init__(self) -> None:
        self.questions = [FakeQuestion()]


@pytest.mark.asyncio
async def test_run_generation_retries_until_mock_exam_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mock_exam이 뒤늦게 보이면 재시도 후 생성·저장 경로로 진입한다."""
    load_results: list[dict[str, object] | None] = [None, None, _exam_context()]
    sleep_calls: list[float] = []
    persisted: dict[str, object] = {}

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    async def fake_load_exam_context(conn: object, exam_id: str) -> dict[str, object] | None:
        return load_results.pop(0)

    async def fake_build_source_text(conn: object, course_id: str, topic_text: str | None) -> str:
        return "스택과 큐의 핵심 개념, 연산 복잡도, 활용 사례를 비교하는 학습 자료입니다. " * 5

    async def fake_generate_exam_forge(request: ExamForgeRequest) -> FakeResponse:
        persisted["subject"] = request.subject
        return FakeResponse()

    async def fake_persist_exam_result(
        conn: object,
        *,
        exam_id: str,
        questions: list[dict[str, object]],
    ) -> int:
        persisted["exam_id"] = exam_id
        persisted["questions"] = questions
        return len(questions)

    _patch_runtime(
        monkeypatch,
        fake_sleep=fake_sleep,
        fake_load_exam_context=fake_load_exam_context,
        fake_build_source_text=fake_build_source_text,
        fake_generate_exam_forge=fake_generate_exam_forge,
        fake_persist_exam_result=fake_persist_exam_result,
    )

    await spring_adapter._run_generation(_request())

    assert sleep_calls == [spring_adapter._SPRING_COMMIT_RETRY_DELAY_SEC] * 2
    assert persisted["exam_id"] == "exam-1"
    assert persisted["subject"] == "자료구조"
    assert persisted["questions"] == [{"question_id": "q1", "stem": "테스트 문항"}]


@pytest.mark.asyncio
async def test_run_generation_logs_and_returns_after_retry_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """모든 재시도 후에도 mock_exam이 없으면 예외 없이 기존 종료 동작을 유지한다."""
    load_count = {"value": 0}
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    async def fake_load_exam_context(conn: object, exam_id: str) -> dict[str, object] | None:
        load_count["value"] += 1
        return None

    async def fail_build_source_text(conn: object, course_id: str, topic_text: str | None) -> str:
        raise AssertionError("mock_exam이 없으면 source_text를 만들면 안 된다")

    async def fail_generate_exam_forge(request: ExamForgeRequest) -> FakeResponse:
        raise AssertionError("mock_exam이 없으면 생성 파이프라인에 진입하면 안 된다")

    async def fail_persist_exam_result(
        conn: object,
        *,
        exam_id: str,
        questions: list[dict[str, object]],
    ) -> int:
        raise AssertionError("mock_exam이 없으면 저장하면 안 된다")

    _patch_runtime(
        monkeypatch,
        fake_sleep=fake_sleep,
        fake_load_exam_context=fake_load_exam_context,
        fake_build_source_text=fail_build_source_text,
        fake_generate_exam_forge=fail_generate_exam_forge,
        fake_persist_exam_result=fail_persist_exam_result,
    )
    caplog.set_level(logging.ERROR, logger=spring_adapter.__name__)

    await spring_adapter._run_generation(_request())

    assert load_count["value"] == spring_adapter._SPRING_COMMIT_RETRY_ATTEMPTS
    assert sleep_calls == [spring_adapter._SPRING_COMMIT_RETRY_DELAY_SEC] * 4
    assert "[mock-exam] mock_exam 없음" in caplog.text


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fake_sleep: Callable[[float], Awaitable[None]],
    fake_load_exam_context: Callable[[object, str], Awaitable[dict[str, object] | None]],
    fake_build_source_text: Callable[[object, str, str | None], Awaitable[str]],
    fake_generate_exam_forge: Callable[[ExamForgeRequest], Awaitable[FakeResponse]],
    fake_persist_exam_result: Callable[..., Awaitable[int]],
) -> None:
    """외부 DB/LLM/저장을 테스트 대역으로 고정한다."""
    monkeypatch.setattr(spring_adapter, "get_connection", lambda: FakeConnectionManager())
    monkeypatch.setattr(spring_adapter.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(spring_adapter, "load_exam_context", fake_load_exam_context)
    monkeypatch.setattr(spring_adapter, "build_source_text", fake_build_source_text)
    monkeypatch.setattr(examforge_module, "generate_exam_forge", fake_generate_exam_forge)
    monkeypatch.setattr(spring_adapter, "persist_exam_result", fake_persist_exam_result)


def _request() -> spring_adapter.MockExamGenerateRequest:
    """Spring generateExam 요청 바디를 만든다."""
    return spring_adapter.MockExamGenerateRequest(
        examId="exam-1",
        courseId="course-1",
        examType="중간고사",
        questionCount=5,
        difficulty="medium",
        focusTopics=["스택", "큐"],
    )


def _exam_context() -> dict[str, object]:
    """public.mock_exam + public.course 조인 결과를 만든다."""
    return {
        "exam_id": "exam-1",
        "course_id": "course-1",
        "course_name": "알고리즘",
        "subject": "자료구조",
        "topic_text": "스택과 큐",
    }
