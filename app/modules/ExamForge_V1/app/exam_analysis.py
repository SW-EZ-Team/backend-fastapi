"""모의고사 AI 총평(약점 진단) 로직 모듈.

채점이 끝난 결과를 받아 codex(텍스트 커넥터)로 개인 맞춤 학습 총평을 생성한다.
Spring submitExam이 이 결과를 동기 호출해 결과지의 analysis 필드를 채운다.

설계 원칙:
- 읽기 전용 분석 생성 — 정답/채점 스키마를 건드리지 않는다.
- codex 1회 호출이라 예산 카운터는 단순히 1짜리로 격리한다.
- codex 실패는 조용히 삼키지 않고 로깅한 뒤 AnalysisGenerationError로 올린다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.ExamForge_V1.app._analysis_prompt import (
    build_user_prompt,
    restore_option_text,
    system_prompt,
)
from app.modules.ExamForge_V1.common.ai_bridge import (
    ChapterAIRequest,
    LLMBudgetCounter,
    get_text_connector,
    set_current_budget,
)
from app.modules.ExamForge_V1.common.ai_bridge import _current_budget
from app.modules.ExamForge_V1.common.errors import BudgetExceededError
from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)

# codex 호출 파라미터 — 총평은 1회 생성이라 토큰·온도를 보수적으로 둔다
_MAX_TOKENS = 2000
_TEMPERATURE = 0.5
# 총평 1회 호출 전용 예산(서킷 브레이커) — 분석은 단일 호출이라 1로 충분하다
_ANALYSIS_BUDGET = 1


class AnalysisGenerationError(RuntimeError):
    """codex 총평 생성 실패. 라우터가 잡아 폴백/503으로 변환한다."""


class MockExamResultItem(BaseModel):
    """문항별 채점 결과 — Spring과 합의된 고정 계약."""

    model_config = {"extra": "ignore"}

    questionIdx: int
    questionText: str
    correct: bool
    options: str  # 보기 텍스트의 JSON 배열 문자열
    selectedOption: str  # 0-based 인덱스 문자열
    correctOption: str  # 0-based 인덱스 문자열
    explanation: str = ""


class MockExamAnalyzeRequest(BaseModel):
    """POST /api/mock-exams/analyze 요청 바디 — Spring 고정 계약."""

    model_config = {"extra": "ignore"}

    examId: str = Field(min_length=1)
    subject: str = ""
    score: int = Field(ge=0)
    totalPoints: int = Field(ge=0)
    grade: str = ""
    results: list[MockExamResultItem] = Field(default_factory=list)


class MockExamAnalyzeResponse(BaseModel):
    """응답 바디 — 정확히 {"analysis": "..."}."""

    analysis: str


def _format_question_line(item: MockExamResultItem) -> str:
    """문항 하나를 프롬프트용 한 줄로 변환한다(보기 텍스트 복원 포함)."""
    selected = restore_option_text(item.options, item.selectedOption)
    correct = restore_option_text(item.options, item.correctOption)
    mark = "정답" if item.correct else "오답"
    line = (
        f"[{mark}] {item.questionIdx}번. {item.questionText}\n"
        f"  - 내가 고른 보기: {selected}\n"
        f"  - 정답 보기: {correct}"
    )
    if item.explanation.strip():
        line += f"\n  - 해설: {item.explanation.strip()}"
    return line


def _build_request(req: MockExamAnalyzeRequest) -> ChapterAIRequest:
    """분석 요청을 codex용 ChapterAIRequest로 조립한다."""
    is_perfect = req.totalPoints > 0 and req.score >= req.totalPoints
    question_lines = [_format_question_line(item) for item in req.results]
    user = build_user_prompt(
        subject=req.subject or "모의고사",
        score=req.score,
        total_points=req.totalPoints,
        grade=req.grade or "-",
        question_lines=question_lines,
        is_perfect=is_perfect,
    )
    return ChapterAIRequest(
        system=system_prompt(),
        user=user,
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
    )


async def generate_analysis(req: MockExamAnalyzeRequest) -> str:
    """채점 결과를 받아 codex로 총평 텍스트를 생성해 반환한다.

    codex 호출 실패 시 AnalysisGenerationError로 올린다(로깅 필수, 조용한 삼킴 금지).
    """
    ai_req = _build_request(req)
    connector = get_text_connector()

    # 총평 1회 호출 전용 예산 카운터를 컨텍스트에 격리한다(누수 방지)
    budget = LLMBudgetCounter(_ANALYSIS_BUDGET)
    token = set_current_budget(budget)
    try:
        resp = await connector.generate(ai_req)
    except (RuntimeError, TimeoutError, BudgetExceededError) as exc:
        # codex 비정상 종료/타임아웃/예산 초과를 정규화해 재발생한다(조용한 삼킴 금지).
        logger.warning("[mock-exam-analyze] codex 총평 생성 실패 — examId=%s: %s", req.examId, exc)
        raise AnalysisGenerationError(str(exc)) from exc
    finally:
        _current_budget.reset(token)

    text = resp.text.strip()
    if not text:
        logger.warning("[mock-exam-analyze] codex 빈 응답 — examId=%s", req.examId)
        raise AnalysisGenerationError("codex가 빈 총평을 반환했어요.")
    logger.info("[mock-exam-analyze] 총평 생성 완료 — examId=%s, %d자", req.examId, len(text))
    return text
