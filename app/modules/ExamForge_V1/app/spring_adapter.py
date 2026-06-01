"""Spring ↔ FastAPI 모의고사 연결 어댑터 — Spring MockExamService가 호출하는 경로.

Spring generateExam()이 MockExam을 status=GENERATING으로 저장한 뒤
fire-and-forget(Void)으로 POST /api/mock-exams/generate 를 호출한다(응답 본문 무시).
어댑터는 즉시 202를 반환하고, 백그라운드에서 ExamForge 파이프라인을 실행해
결과를 public.mock_exam_question 에 저장하고 mock_exam.status 를 READY 로 전이한다.
이후 Spring이 getExamDetail(READY 상태에서만 문항 조회)로 폴링해 결과를 읽는다.

연결 키: examId(=public.mock_exam.id), courseId(=public.course.id).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.modules.ExamForge_V1.db.mockexam_persistence import (
    build_source_text,
    load_exam_context,
    persist_exam_result,
)
from app.modules.ExamForge_V1.schemas.request import ExamConfig, ExamForgeRequest
from common.db import get_connection

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mock-exams", tags=["mock-exams"])

# Spring difficulty(easy/medium/hard) → ExamForge 난이도 분포(1~5, 합 1.0)
# 합이 정확히 1.0이 되도록 구성한다(ExamConfig validator가 강제).
_DIFFICULTY_DISTRIBUTIONS: dict[str, dict[int, float]] = {
    "easy": {1: 0.4, 2: 0.35, 3: 0.2, 4: 0.05, 5: 0.0},
    "medium": {1: 0.2, 2: 0.3, 3: 0.3, 4: 0.15, 5: 0.05},
    "hard": {1: 0.05, 2: 0.15, 3: 0.3, 4: 0.3, 5: 0.2},
}

# ExamForge source_text 최소 길이(100자) 미달 시 채우는 안전 패딩 안내 문구
_SOURCE_MIN_LEN = 100


class MockExamGenerateRequest(BaseModel):
    """Spring MockExamService.generateExam 이 보내는 바디."""

    examId: str = Field(min_length=1)
    courseId: str = Field(min_length=1)
    examType: str = ""
    questionCount: int = Field(default=10, ge=1, le=50)
    difficulty: str = "medium"
    focusTopics: list[str] | None = None
    timeLimit: int | None = None


@router.post("/generate", status_code=202)
async def generate_mock_exam(
    req: MockExamGenerateRequest, background_tasks: BackgroundTasks
) -> dict[str, object]:
    """모의고사 생성을 비동기로 시작하고 202를 즉시 반환한다."""
    background_tasks.add_task(_run_generation, req)
    return {"accepted": True, "examId": req.examId}


async def _run_generation(req: MockExamGenerateRequest) -> None:
    """ExamForge로 모의고사를 생성하고 public 스키마에 저장한다.

    실패는 로깅하고 삼키지 않는다(상태는 GENERATING 유지 → Spring이 미완료로 인지).
    """
    async with get_connection() as conn:
        ctx = await load_exam_context(conn, req.examId)
        if ctx is None:
            _LOG.error("[mock-exam] mock_exam 없음 — examId=%s", req.examId)
            return
        source_text = await build_source_text(conn, req.courseId, ctx.get("topic_text"))

    source_text = _ensure_min_source(source_text, ctx, req)
    forge_req = _build_forge_request(req, ctx, source_text)

    # 순환 import 회피 — 모듈 __init__의 라이브러리 진입점을 지연 import 한다
    from app.modules.ExamForge_V1 import generate_exam_forge

    response = await generate_exam_forge(forge_req)
    questions = [q.model_dump() for q in response.questions]

    async with get_connection() as conn:
        saved = await persist_exam_result(conn, exam_id=req.examId, questions=questions)

    if saved == 0:
        _LOG.error("[mock-exam] 저장 가능한 객관식 문항 0개 — examId=%s", req.examId)
        return
    _LOG.info("[mock-exam] 저장 완료 — examId=%s, 문항 %d개", req.examId, saved)


def _build_forge_request(
    req: MockExamGenerateRequest, ctx: dict, source_text: str
) -> ExamForgeRequest:
    """Spring 요청 + course 메타를 ExamForge 입력 스키마로 변환한다."""
    subject = (ctx.get("subject") or ctx.get("course_name") or req.examType or "모의고사").strip()
    distribution = _DIFFICULTY_DISTRIBUTIONS.get(req.difficulty.lower(), _DIFFICULTY_DISTRIBUTIONS["medium"])
    config = ExamConfig(
        # ExamForge는 최소 5문항을 요구한다 — Spring이 5 미만을 보내도 실패하지 않도록 보정한다.
        total_questions=max(5, req.questionCount),
        time_limit_minutes=req.timeLimit or 60,
        locale="ko",
        category="korean",
        question_types=["ko_multiple_choice_5"],  # Spring 채점은 객관식 단일 정답
        difficulty_distribution=dict(distribution),
    )
    return ExamForgeRequest(source_text=source_text, subject=subject, exam_config=config)


def _ensure_min_source(source_text: str, ctx: dict, req: MockExamGenerateRequest) -> str:
    """source_text가 ExamForge 최소 길이(100자) 미달이면 메타로 보강한다."""
    text = source_text.strip()
    if len(text) >= _SOURCE_MIN_LEN:
        return text
    subject = (ctx.get("subject") or ctx.get("course_name") or "일반").strip()
    topics = ", ".join(req.focusTopics or []) or subject
    padding = (
        f"과목 {subject} 의 {req.examType or '모의고사'} 출제를 위한 학습 범위 요약. "
        f"집중 주제: {topics}. 위 주제를 중심으로 핵심 개념과 적용을 평가한다."
    )
    return (text + "\n" + padding).strip()
