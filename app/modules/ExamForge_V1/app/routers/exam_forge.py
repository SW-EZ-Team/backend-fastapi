"""모의고사 생성 API 라우터."""
from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import APIRouter, HTTPException

from app.modules.ExamForge_V1.common.ai_bridge import LLMBudgetCounter, set_current_budget
from app.modules.ExamForge_V1.common.config import (
    max_retries,
    pipeline_llm_budget_for,
    pipeline_llm_reserve_for,
    pipeline_timeout_sec,
)
from app.modules.ExamForge_V1.common.errors import BudgetExceededError
from app.modules.ExamForge_V1.grading.engine import grade_submission
from app.modules.ExamForge_V1.grading.exceptions import (
    AnswerKeyIntegrityError,
    RubricGradingError,
)
from app.modules.ExamForge_V1.grading.seal import attach_answer_key_seal
from app.modules.ExamForge_V1.schemas.grading import (
    GradeSubmissionRequest,
    GradeSubmissionResponse,
)
from app.modules.ExamForge_V1.schemas.request import ExamForgeRequest
from app.modules.ExamForge_V1.schemas.response import ExamForgeResponse

router = APIRouter(prefix="/api/exam-forge", tags=["exam-forge"])


@router.post("/generate", response_model=ExamForgeResponse)
async def generate_exam_forge(request: ExamForgeRequest) -> ExamForgeResponse:
    """모의고사를 생성한다."""
    start_time = time.time()
    exam_id = f"exam_{uuid.uuid4().hex[:12]}"

    # LLM 호출 예산 서킷 브레이커 초기화 — 문항 수에 비례한 예산 + 해설 생성 예약분.
    # reserve 풀은 upstream 재시도가 소진해도 해설 생성이 굶지 않게 보호한다.
    total_questions = request.exam_config.total_questions
    budget = LLMBudgetCounter(
        budget=pipeline_llm_budget_for(total_questions),
        reserve=pipeline_llm_reserve_for(total_questions),
    )
    budget_token = set_current_budget(budget)

    initial_state = {
        "source_text": request.source_text,
        "subject": request.subject,
        "exam_config": request.exam_config.model_dump(),
        "locale": request.exam_config.locale,
        "category": request.exam_config.category,
        "retry_count": 0,
        "max_retries": max_retries(),
        "pipeline_status": "parsing",
        "error_message": None,
        "exam_id": exam_id,
        "timings": {"start": start_time},
        "llm_call_count": 0,
        "llm_budget_exceeded": False,
    }

    from app.modules.ExamForge_V1.pipeline.graph import get_compiled_graph
    graph = get_compiled_graph()

    from app.modules.ExamForge_V1.common.ai_bridge import _current_budget

    final_state: dict | None = None
    try:
        timeout_sec = pipeline_timeout_sec()
        final_state = await asyncio.wait_for(
            graph.ainvoke(initial_state),
            timeout=float(timeout_sec),
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"모의고사 생성 시간 초과 ({pipeline_timeout_sec()}초 제한)",
        )
    except BudgetExceededError as e:
        # 서킷 브레이커 발동 — 부분 결과가 있으면 반환, 없으면 에러
        raise HTTPException(
            status_code=429,
            detail=f"LLM 호출 예산 초과로 파이프라인 중단: {e}",
        )
    except (RuntimeError, ValueError, TypeError, KeyError) as e:
        detail = f"파이프라인 실행 실패: {str(e)[:200]}"
        # 파이프라인 상태가 확보된 경우 pipeline_status를 오류 상세에 포함한다
        if final_state is not None and final_state.get("pipeline_status"):
            # pipeline_status 키 누락 시 "unknown"으로 폴백해 KeyError 방지
            detail += f" [pipeline_status={final_state.get('pipeline_status', 'unknown')}]"
        raise HTTPException(status_code=500, detail=detail) from e
    finally:
        # 예산 카운터 컨텍스트 변수 정리 — 누수 방지
        _current_budget.reset(budget_token)

    status = final_state.get("pipeline_status", "unknown")

    # 완료/부분 완료 상태는 정상 응답 반환 — error_message 가 있어도 HTTP 에러 아님
    if status in ("complete", "done", "partial"):
        final_state = attach_answer_key_seal(final_state)
        return ExamForgeResponse.from_state(final_state)

    # 오류/실패 상태 — pipeline_status 에 따라 적절한 HTTP 코드 사용
    error_msg = final_state.get("error_message", "알 수 없는 파이프라인 오류")
    # "error" 는 인프라 오류(500), "failed" 등은 품질 미달(422)
    code = 500 if status == "error" else 422
    raise HTTPException(status_code=code, detail=f"{error_msg} [status={status}]")


@router.post("/grade-submission", response_model=GradeSubmissionResponse)
async def grade_exam_submission(
    request: GradeSubmissionRequest,
) -> GradeSubmissionResponse:
    """응시자가 제출한 답안을 실제 채점 규칙으로 채점한다."""
    budget = LLMBudgetCounter()
    budget_token = set_current_budget(budget)
    from app.modules.ExamForge_V1.common.ai_bridge import _current_budget

    try:
        return await asyncio.wait_for(
            grade_submission(request),
            timeout=float(pipeline_timeout_sec()),
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"제출 답안 채점 시간 초과 ({pipeline_timeout_sec()}초 제한)",
        ) from exc
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail=f"LLM 호출 예산 초과로 채점 중단: {exc}",
        ) from exc
    except RubricGradingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AnswerKeyIntegrityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"채점 엔진 실행 실패: {exc}") from exc
    finally:
        _current_budget.reset(budget_token)


@router.get("/templates")
async def list_templates(
    locale: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """사용 가능한 템플릿 목록을 반환한다."""
    from app.modules.ExamForge_V1.templates.catalog import list_template_specs

    return [
        spec.to_dict()
        for spec in list_template_specs(locale=locale, category=category)
    ]


@router.get("/paper-templates")
async def list_paper_templates() -> list[dict]:
    """사용 가능한 실전 시험지 틀 목록을 반환한다."""
    from app.modules.ExamForge_V1.templates.catalog import exam_paper_options

    return exam_paper_options()


@router.get("/health")
async def health() -> dict[str, str]:
    """라우터 헬스체크."""
    return {"status": "ok", "service": "exam-forge"}
