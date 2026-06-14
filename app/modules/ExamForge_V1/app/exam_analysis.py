"""모의고사 AI 총평(약점 진단) 로직 모듈.

채점이 끝난 결과를 받아 codex(텍스트 커넥터)로 개인 맞춤 학습 총평을 생성한다.
Spring submitExam이 이 결과를 동기 호출해 결과지의 analysis 필드를 채운다.

설계 원칙:
- 읽기 전용 분석 생성 — 정답/채점 스키마를 건드리지 않는다.
- codex 1회 호출이라 예산 카운터는 단순히 1짜리로 격리한다.
- codex 실패는 조용히 삼키지 않고 로깅한 뒤 AnalysisGenerationError로 올린다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.modules.ExamForge_V1.app._analysis_prompt import (
    build_user_prompt,
    restore_option_text,
    split_weak_topics,
    system_prompt,
)
from app.modules.ExamForge_V1.app._analysis_sanitize import sanitize_analysis
from app.modules.ExamForge_V1.common.ai_bridge import (
    ChapterAIRequest,
    LLMBudgetCounter,
    get_grading_connector,
    set_current_budget,
)
from app.modules.ExamForge_V1.common.ai_bridge import _current_budget
from app.modules.ExamForge_V1.common.errors import BudgetExceededError
from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)

# codex 호출 파라미터 — 총평은 1회 생성이라 토큰·온도를 보수적으로 둔다.
# 한국어 350~700자 본문(약 350~700 토큰) + 약점주제 줄이 절대 잘리지 않도록 여유를 둔다.
# 일부 모델이 사고/초안을 누출하면 그만큼 본문 토큰을 잡아먹어 본문이 중간에 잘리므로
# 사고 누출 자체는 프롬프트(_analysis_prompt)와 정제(_analysis_sanitize)로 막고,
# 토큰은 본문이 안 잘릴 만큼 넉넉히 둔다.
_MAX_TOKENS = 2048
_TEMPERATURE = 0.5
# 총평 1회 호출 전용 예산(서킷 브레이커) — 분석은 단일 호출이라 1로 충분하다
_ANALYSIS_BUDGET = 1
# 정제 후 본문이 비었을 때(메타만 누출된 극단 케이스) 노출할 안전 폴백 문구.
_EMPTY_BODY_FALLBACK = "총평 본문을 생성하지 못했어요. 점수와 문항별 해설을 참고해 주세요."


class AnalysisGenerationError(RuntimeError):
    """codex 총평 생성 실패. 라우터가 잡아 폴백/503으로 변환한다."""


class MockExamResultItem(BaseModel):
    """문항별 채점 결과 — Spring과 합의된 고정 계약.

    selectedText/correctText는 examgrading(다유형) 경로 확장 필드다.
    값이 있으면 인덱스 복원 대신 텍스트를 그대로 사용한다(단답·서술·빈칸 등 비객관식 대응).
    """

    model_config = {"extra": "ignore"}

    questionIdx: int
    questionText: str
    correct: bool
    options: str = ""  # 보기 텍스트의 JSON 배열 문자열 (객관식 전용, 비객관식은 빈 문자열)
    selectedOption: str = ""  # 0-based 인덱스 문자열
    correctOption: str = ""  # 0-based 인덱스 문자열
    selectedText: str = ""  # 제출 답 사람이 읽는 텍스트 (있으면 인덱스 복원보다 우선)
    correctText: str = ""  # 정답 사람이 읽는 텍스트 (있으면 인덱스 복원보다 우선)
    explanation: str = ""

    @field_validator(
        "questionText",
        "options",
        "selectedOption",
        "correctOption",
        "selectedText",
        "correctText",
        "explanation",
        mode="before",
    )
    @classmethod
    def _none_to_empty(cls, value: object) -> object:
        """Spring(Jackson)이 null을 보내는 필드를 빈 문자열로 흡수한다.

        record 필드 하나가 null이어도 422로 분석 전체가 실패하지 않게 한다
        (분석은 채점의 부가 기능 — 한 필드 결손이 전체 실패 사유가 되어선 안 된다).
        """
        return "" if value is None else value


class MockExamAnalyzeRequest(BaseModel):
    """POST /api/mock-exams/analyze 요청 바디 — Spring 고정 계약."""

    model_config = {"extra": "ignore"}

    examId: str = Field(min_length=1)
    subject: str = ""
    score: int = Field(ge=0)
    totalPoints: int = Field(ge=0)
    grade: str = ""
    results: list[MockExamResultItem] = Field(default_factory=list)

    @field_validator("subject", "grade", mode="before")
    @classmethod
    def _none_to_empty(cls, value: object) -> object:
        """Spring(Jackson)이 null을 보내는 선택 필드를 빈 문자열로 흡수한다."""
        return "" if value is None else value


class MockExamAnalyzeResponse(BaseModel):
    """응답 바디 — analysis(총평 본문) + weakTopics(약점 주제 목록).

    weakTopics는 mock_exam_submission.analysis JSON에 저장되어
    ChapterStudio 약점 집계(weakness_aggregator)가 읽는 핵심 필드다.
    """

    analysis: str
    weakTopics: list[str] = Field(default_factory=list)


def _format_question_line(item: MockExamResultItem) -> str:
    """문항 하나를 프롬프트용 한 줄로 변환한다(보기 텍스트 복원 포함)."""
    # 텍스트 필드가 오면 그대로 사용(비객관식), 없으면 보기 인덱스에서 복원(레거시 객관식)
    selected = item.selectedText.strip() or restore_option_text(item.options, item.selectedOption)
    correct = item.correctText.strip() or restore_option_text(item.options, item.correctOption)
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
        # 총평 기본 모델은 Claude Sonnet(추론을 본문에 누출하지 않음)이다.
        # 단, gemini 폴백 시엔 gemini-3.x 인라인 reasoning 이 본문에 누출되므로(실측 2026-06-14)
        # thinking_budget=0 으로 추론을 꺼 누출을 차단한다(Anthropic 커넥터는 이 extra 를 무시).
        extra={"thinking_budget": 0},
    )


async def generate_analysis(req: MockExamAnalyzeRequest) -> tuple[str, list[str]]:
    """채점 결과를 받아 codex로 (총평 본문, 약점 주제 목록)을 생성해 반환한다.

    약점 주제는 총평 마지막 줄('약점주제: a | b | c')을 파싱해 분리한다 —
    형식 누락 시 빈 목록으로 폴백하고 경고 로깅한다.
    codex 호출 실패 시 AnalysisGenerationError로 올린다(로깅 필수, 조용한 삼킴 금지).
    """
    ai_req = _build_request(req)
    connector = get_grading_connector()

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

    # 사고/스크래치패드/영문 메타 발화를 먼저 제거한 뒤 약점주제 줄을 분리한다.
    # (정제 → 분리 순서가 중요: 메타 줄이 약점주제 줄보다 뒤에 오면 split이 오인할 수 있다.)
    sanitized = sanitize_analysis(text)
    if sanitized != text:
        logger.info(
            "[mock-exam-analyze] 메타/사고 누출 정제 — examId=%s, %d자→%d자",
            req.examId,
            len(text),
            len(sanitized),
        )

    body, weak_topics = split_weak_topics(sanitized)
    is_perfect = req.totalPoints > 0 and req.score >= req.totalPoints

    # 정제 후 본문이 비면(메타만 누출된 극단 케이스) 안전 폴백 문구로 대체한다.
    if not body.strip():
        logger.warning(
            "[mock-exam-analyze] 정제 후 본문 공백 — 폴백 문구 사용, examId=%s",
            req.examId,
        )
        body = _EMPTY_BODY_FALLBACK
    if not weak_topics and not is_perfect:
        # 약점주제 줄 누락 — 본문은 정상 사용하고 빈 목록을 명시적으로 로깅한다
        logger.warning(
            "[mock-exam-analyze] 약점주제 줄 누락 — weakTopics 빈 목록으로 반환, examId=%s",
            req.examId,
        )
    logger.info(
        "[mock-exam-analyze] 총평 생성 완료 — examId=%s, %d자, 약점주제 %d개",
        req.examId,
        len(body),
        len(weak_topics),
    )
    return body, weak_topics
