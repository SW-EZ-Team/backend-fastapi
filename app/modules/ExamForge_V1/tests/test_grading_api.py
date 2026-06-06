"""ExamForge 제출 채점 API 테스트."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.ExamForge_V1.grading.seal import create_answer_key_seal
from app.modules.ExamForge_V1.schemas.grading import GradeSubmissionRequest, SubmittedAnswer
from app.modules.ExamForge_V1.tests.grading_samples import choice_question


@pytest.mark.asyncio
async def test_grade_submission_endpoint_executes_business_logic() -> None:
    """라우터 핸들러가 실제 채점 엔진 결과를 그대로 반환한다."""
    from app.modules.ExamForge_V1.app.routers.exam_forge import grade_exam_submission

    questions = [choice_question()]
    request = GradeSubmissionRequest(
        attempt_id="attempt-endpoint",
        exam_id="exam-endpoint",
        answer_key_seal=create_answer_key_seal("exam-endpoint", questions),
        questions=questions,
        submitted_answers=[SubmittedAnswer(question_id="q-choice", answer="2")],
    )

    response = await grade_exam_submission(request)

    assert response.total_score == pytest.approx(2.0)
    assert response.results[0].is_correct is True


def test_http_endpoint_rejects_invalid_answer_key_seal_in_enforce_mode() -> None:
    """HTTP 표면에서 위조된 정답 키 서명을 ENFORCE 모드에서 403으로 거부한다.

    advisory 모드(기본)에서는 seal 불일치가 채점 차단을 일으키지 않으므로,
    EXAMFORGE_SEAL_ENFORCE=true 강제 모드일 때만 403이 반환되는지 검증한다.
    """
    from app.modules.ExamForge_V1.app.routers.exam_forge import router

    app = FastAPI()
    app.include_router(router)

    with patch(
        "app.modules.ExamForge_V1.grading.engine.seal_enforce_mode",
        return_value=True,
    ):
        response = TestClient(app).post(
            "/api/exam-forge/grade-submission",
            json={
                "attempt_id": "attempt-forged",
                "exam_id": "exam-forged",
                "answer_key_seal": "v1." + ("x" * 43),
                "questions": [choice_question().model_dump(mode="json")],
                "submitted_answers": [{"question_id": "q-choice", "answer": "2"}],
            },
        )

    assert response.status_code == 403


def test_router_exposes_grade_submission_endpoint() -> None:
    """FastAPI 라우터가 제출 채점 엔드포인트를 공개한다."""
    from app.modules.ExamForge_V1.app.routers.exam_forge import router

    paths = {route.path for route in router.routes}
    assert "/api/exam-forge/grade-submission" in paths
