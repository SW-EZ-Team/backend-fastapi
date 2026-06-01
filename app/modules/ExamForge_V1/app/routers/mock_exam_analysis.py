"""Spring ↔ FastAPI 모의고사 AI 총평 라우터.

Spring submitExam이 채점 끝난 결과를 보내 동기 호출하면, codex로 총평을 생성해
결과지의 analysis 필드를 채울 문자열을 반환한다.

엔드포인트: POST /api/mock-exams/analyze
응답: {"analysis": "<한국어 총평 문자열>"}

실패 정책: codex 호출 실패 시 빈 analysis가 아닌 명시적 폴백 문구를 200으로 반환한다.
Spring이 analysis=null 로도 처리 가능하도록, 폴백 문구는 사용자에게 그대로 보여줄 수
있는 안내문으로 둔다(에러를 조용히 삼키지 않고 라우터에서 로깅).
"""
from __future__ import annotations

from fastapi import APIRouter

from app.modules.ExamForge_V1.app.exam_analysis import (
    AnalysisGenerationError,
    MockExamAnalyzeRequest,
    MockExamAnalyzeResponse,
    generate_analysis,
)
from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/mock-exams", tags=["mock-exams"])

# codex 실패 시 사용자에게 그대로 노출할 명시적 폴백 문구
_FALLBACK_ANALYSIS = "총평 생성에 실패했어요. 점수와 문항별 해설을 참고해 주세요."


@router.post("/analyze", response_model=MockExamAnalyzeResponse)
async def analyze_mock_exam(req: MockExamAnalyzeRequest) -> MockExamAnalyzeResponse:
    """채점 결과를 받아 codex 총평을 생성해 반환한다.

    codex 실패 시에도 200 + 폴백 문구를 반환해 Spring 흐름을 끊지 않는다.
    """
    try:
        analysis = await generate_analysis(req)
    except AnalysisGenerationError as exc:
        # 이미 generate_analysis에서 로깅됨 — 라우터에서도 폴백 사용 사실을 남긴다
        logger.warning(
            "[mock-exam-analyze] 폴백 총평 반환 — examId=%s: %s", req.examId, exc
        )
        analysis = _FALLBACK_ANALYSIS
    return MockExamAnalyzeResponse(analysis=analysis)
