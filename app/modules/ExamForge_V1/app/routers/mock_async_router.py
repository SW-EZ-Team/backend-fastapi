"""ExamForge_V1 비동기 모의고사 생성 라우터.

Spring이 POST /api/exam-forge/mock/generate-async 를 호출하면
202를 즉시 반환하고, BackgroundTask로 ExamForge 파이프라인을 실행한다.

생성 완료 시 Spring /internal/exam-attempts/{attempt_id}/generated 콜백을 전송한다.
실패 시   Spring /internal/exam-attempts/{attempt_id}/generation-failed 콜백을 전송한다.

설계 원칙:
- 기존 /api/exam-forge/generate 파이프라인 로직을 직접 재사용한다 (중복 없음).
- AssignmentGrader_V1 과 임포트 교차 없음 — ExamForge_V1 전용 콜백 모듈만 사용.
- question_types 는 요청 그대로 전달 — 객관식 단일 강제 금지.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.modules.ExamForge_V1.common.ai_bridge import (
    LLMBudgetCounter,
    _current_budget,
    set_current_budget,
)
from app.modules.ExamForge_V1.common.config import (
    max_retries,
    pipeline_llm_budget_for,
    pipeline_llm_reserve_for,
    pipeline_timeout_sec,
)
from app.modules.ExamForge_V1.grading.seal import attach_answer_key_seal
from app.modules.ExamForge_V1.mock_generation_callback import (
    MockGenerationCallbackError,
    send_generation_failed_callback,
    send_generation_success_callback,
)
from app.modules.ExamForge_V1.schemas.request import ExamConfig, ExamForgeRequest

_LOG = logging.getLogger(__name__)

# ExamForge source_text 최소 길이(100자) 미달 시 채우는 안전 패딩용 최소 길이
_SOURCE_MIN_LEN = 100
# Spring 요청 문항 수 하한 — ExamForge 최소 요건(5문항) 보정
_MIN_QUESTION_COUNT = 5

router = APIRouter(prefix="/api/exam-forge/mock", tags=["exam-forge-mock-async"])


class MockGenerateAsyncRequest(BaseModel):
    """Spring이 비동기 모의고사 생성 트리거 시 보내는 바디."""

    attempt_id: str = Field(min_length=1, max_length=120)
    course_id: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=200)
    topic: str | None = Field(default=None, max_length=500)
    question_count: int = Field(default=10, ge=1, le=100)
    # 다유형 지원 — Spring이 원하는 템플릿 ID 목록 그대로 전달
    question_types: list[str] = Field(
        default_factory=lambda: ["ko_multiple_choice_5"], min_length=1
    )
    pass_percentage: float = Field(default=60.0, ge=0.0, le=100.0)


@router.post("/generate-async", status_code=202)
async def generate_mock_exam_async(
    req: MockGenerateAsyncRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    """비동기 모의고사 생성 트리거 엔드포인트 — 즉시 202를 반환한다.

    생성 작업은 BackgroundTask로 실행되며 결과는 Spring 콜백으로 전달된다.
    인증은 상위 미들웨어(X-API-Key)가 처리한다.
    """
    background_tasks.add_task(_run_async_generation, req)
    return {"accepted": True, "attempt_id": req.attempt_id}


async def _run_async_generation(req: MockGenerateAsyncRequest) -> None:
    """ExamForge 파이프라인을 실행하고 Spring에 콜백을 전송한다.

    성공: send_generation_success_callback 호출
    실패: send_generation_failed_callback 호출 (예외가 콜백 외부로 전파되지 않도록 한다)
    """
    try:
        response, seal = await _execute_exam_forge_pipeline(req)

        # 생성된 문항 목록 직렬화 — Question 모델 dict 형태로 변환
        questions = [q.model_dump() for q in response.questions]

        # pipeline_outcome이 failed_* 계열이면 품질 기준 미달로 실패 콜백 전송.
        # format_output_node가 failed_no_valid_questions·failed_quality_gate·
        # failed_minimum_threshold 등을 반환할 때 유효 문항이 있어도 Spring에 출고 금지.
        # passed / passed_partial / exhausted(유효분 포함) 만 성공 콜백 대상.
        outcome = response.pipeline_outcome or ""
        if outcome.startswith("failed_"):
            reason = f"파이프라인 품질 기준 미달(outcome={outcome}) — Spring 출고 불가"
            _LOG.warning(
                "[MockAsyncGen] 실패 출고 차단 — attemptId=%s, outcome=%s",
                req.attempt_id,
                outcome,
            )
            _safe_send_failed_callback(req.attempt_id, reason)
            return

        if not questions:
            reason = "생성된 문항이 없음 — 파이프라인 결과 0문항"
            _LOG.error("[MockAsyncGen] 빈 결과 — attemptId=%s", req.attempt_id)
            _safe_send_failed_callback(req.attempt_id, reason)
            return

        # seal은 _execute_exam_forge_pipeline이 final_state에서 직접 추출해 반환한다.
        # response.answer_key_seal 경유 시 str|None 타입으로 인한 빈값 문제를 근본 차단.
        if not seal:
            reason = "answer_key_seal이 비어 있음 — 콜백 전송 불가"
            _LOG.error("[MockAsyncGen] seal 없음 — attemptId=%s", req.attempt_id)
            _safe_send_failed_callback(req.attempt_id, reason)
            return

        _safe_send_success_callback(
            attempt_id=req.attempt_id,
            exam_id=response.exam_id,
            answer_key_seal=seal,
            questions=questions,
        )

    except Exception as exc:
        _LOG.error(
            "[MockAsyncGen] 생성 실패 — attemptId=%s, error=%s",
            req.attempt_id,
            exc,
            exc_info=True,
        )
        _safe_send_failed_callback(req.attempt_id, str(exc)[:500])


async def _execute_exam_forge_pipeline(
    req: MockGenerateAsyncRequest,
) -> "tuple[ExamForgeResponse, str]":  # (응답 객체, answer_key_seal 문자열)
    """ExamForge 파이프라인을 실행하고 (응답, seal) 튜플을 반환한다.

    기존 /api/exam-forge/generate 라우터와 동일한 예산·타임아웃 로직을 따른다.
    question_types는 요청 그대로 전달해 다유형 시험 생성을 보장한다.

    seal은 final_state에서 직접 추출해 반환한다.
    ExamForgeResponse.answer_key_seal(str|None)을 경유하지 않아 빈값 문제를 차단한다.
    """
    from app.modules.ExamForge_V1.common.errors import BudgetExceededError
    from app.modules.ExamForge_V1.pipeline.graph import get_compiled_graph
    from app.modules.ExamForge_V1.schemas.response import ExamForgeResponse

    total_questions = max(_MIN_QUESTION_COUNT, req.question_count)

    # 문항 수에 비례한 LLM 예산 + 해설 예약분 초기화
    budget = LLMBudgetCounter(
        budget=pipeline_llm_budget_for(total_questions),
        reserve=pipeline_llm_reserve_for(total_questions),
    )
    budget_token = set_current_budget(budget)

    start_time = time.time()
    exam_id = f"exam_{uuid.uuid4().hex[:12]}"

    # topic이 있으면 source_text 보강에 사용 — 없으면 subject로 최소 텍스트 구성
    source_text = _build_source_text(req.subject, req.topic, total_questions)

    initial_state = {
        "source_text": source_text,
        "subject": req.subject,
        "exam_config": ExamConfig(
            total_questions=total_questions,
            locale="ko",
            category="korean",
            # question_types를 그대로 전달 — 객관식 단일 강제 금지
            question_types=req.question_types,
            passing_score=req.pass_percentage,
        ).model_dump(),
        "locale": "ko",
        "category": "korean",
        "retry_count": 0,
        "max_retries": max_retries(),
        "pipeline_status": "parsing",
        "error_message": None,
        "exam_id": exam_id,
        "timings": {"start": start_time},
        "llm_call_count": 0,
        "llm_budget_exceeded": False,
    }

    graph = get_compiled_graph()

    try:
        final_state = await asyncio.wait_for(
            graph.ainvoke(initial_state),
            timeout=float(pipeline_timeout_sec()),
        )
    except (BudgetExceededError, asyncio.TimeoutError, RuntimeError, ValueError) as exc:
        raise RuntimeError(f"파이프라인 실행 실패: {exc}") from exc
    finally:
        # 예산 카운터 컨텍스트 변수 누수 방지
        _current_budget.reset(budget_token)

    # attach_answer_key_seal이 state에 answer_key_seal을 주입한 상태 사본을 반환한다.
    # final_state에서 직접 seal을 추출해 ExamForgeResponse.answer_key_seal(str|None) 의
    # 선택적 타입 경유 없이 콜백 페이로드에 전달할 수 있도록 튜플로 반환한다.
    sealed_state = attach_answer_key_seal(final_state)
    seal: str = str(sealed_state.get("answer_key_seal") or "")
    return ExamForgeResponse.from_state(sealed_state), seal


def _build_source_text(subject: str, topic: str | None, question_count: int) -> str:
    """ExamForge 최소 source_text(100자)를 구성한다.

    topic이 있으면 topic 기반 학습 범위 텍스트를 생성하고,
    없으면 subject 기반 안전 패딩으로 최소 길이를 보장한다.
    Spring이 별도 source_text를 제공하지 않는 비동기 생성 경로의 진입 텍스트다.
    """
    base = f"과목: {subject}."
    if topic:
        base = f"과목: {subject}. 주제: {topic}."

    if len(base) >= _SOURCE_MIN_LEN:
        return base

    # 최소 100자 보장 패딩
    padding = (
        f" {subject} 과목의 핵심 개념과 원리를 다루는 모의고사를 출제한다."
        f" 총 {question_count}문항으로 구성하며, 주요 이론과 실제 적용을 균형 있게 평가한다."
        f" 학습자가 해당 과목의 기초부터 심화 내용까지 체계적으로 점검할 수 있도록 출제한다."
    )
    return (base + padding)[:50000]


def _safe_send_success_callback(
    attempt_id: str,
    exam_id: str,
    answer_key_seal: str,
    questions: list[dict],
) -> None:
    """성공 콜백 전송 — 식별자 무결성 실패 시 실패 콜백으로 전환해 Spring을 FAILED로 전이한다.

    MockGenerationCallbackError는 template_id/question_id 누락처럼 콘텐츠 결함에서 발생한다.
    이 경우 Spring에 성공 콜백을 보내지 못했으므로 실패 콜백을 전송해 GENERATING 상태가
    영구 지속되는 것을 방지한다.
    """
    try:
        send_generation_success_callback(
            attempt_id=attempt_id,
            exam_id=exam_id,
            answer_key_seal=answer_key_seal,
            questions=questions,
        )
    except MockGenerationCallbackError as exc:
        _LOG.error(
            "[MockAsyncGen] 성공 콜백 전송 실패 — 실패 콜백으로 전환 "
            "attemptId=%s, error=%s",
            attempt_id,
            exc,
        )
        # 성공 콜백이 차단됐으므로 Spring이 영구 GENERATING 상태에 빠지지 않도록
        # 실패 콜백을 전송한다 (이것도 실패하면 로그만 남긴다).
        _safe_send_failed_callback(attempt_id, f"성공 콜백 차단: {exc}")


def _safe_send_failed_callback(attempt_id: str, reason: str) -> None:
    """실패 콜백 전송 — 전송 실패는 로그만 남기고 추가 예외를 전파하지 않는다."""
    try:
        send_generation_failed_callback(attempt_id=attempt_id, reason=reason)
    except MockGenerationCallbackError as exc:
        _LOG.error(
            "[MockAsyncGen] 실패 콜백 전송 실패 — attemptId=%s, error=%s",
            attempt_id,
            exc,
        )
