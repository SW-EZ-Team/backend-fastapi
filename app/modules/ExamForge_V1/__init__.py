"""AI 모의고사 생성 모듈."""
from app.modules.ExamForge_V1.app.routers.exam_forge import router
from app.modules.ExamForge_V1.app.routers.mock_async_router import (
    router as mock_async_router,
)
from app.modules.ExamForge_V1.app.routers.mock_exam_analysis import (
    router as mock_exam_analysis_router,
)
from app.modules.ExamForge_V1.app.spring_adapter import router as spring_adapter_router
from app.modules.ExamForge_V1.schemas.request import ExamForgeRequest
from app.modules.ExamForge_V1.schemas.response import ExamForgeResponse


async def generate_exam_forge(request: ExamForgeRequest) -> ExamForgeResponse:
    """AI 모의고사를 생성한다.

    라우터와 동일한 안전 제어(예산 카운터 + 타임아웃)를 적용해
    라이브러리 진입점으로 사용될 때도 비용 폭발을 방지한다.
    """
    import asyncio
    import time
    import uuid

    from app.modules.ExamForge_V1.common.ai_bridge import LLMBudgetCounter
    from app.modules.ExamForge_V1.common.ai_bridge import _current_budget
    from app.modules.ExamForge_V1.common.ai_bridge import set_current_budget
    from app.modules.ExamForge_V1.common.config import max_retries
    from app.modules.ExamForge_V1.common.config import pipeline_llm_budget
    from app.modules.ExamForge_V1.common.config import pipeline_timeout_sec
    from app.modules.ExamForge_V1.grading.seal import attach_answer_key_seal
    from app.modules.ExamForge_V1.pipeline.graph import get_compiled_graph

    graph = get_compiled_graph()
    start_time = time.time()
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
        "exam_id": f"exam_{uuid.uuid4().hex[:12]}",
        "timings": {"start": start_time},
    }

    # 예산 서킷 브레이커 초기화
    budget = LLMBudgetCounter(pipeline_llm_budget())
    budget_token = set_current_budget(budget)
    try:
        final_state = await asyncio.wait_for(
            graph.ainvoke(initial_state),
            timeout=float(pipeline_timeout_sec()),
        )
    finally:
        # 예산 카운터 컨텍스트 변수 정리 — 누수 방지
        _current_budget.reset(budget_token)

    return ExamForgeResponse.from_state(attach_answer_key_seal(final_state))


__all__ = [
    "ExamForgeRequest",
    "ExamForgeResponse",
    "generate_exam_forge",
    "mock_async_router",
    "mock_exam_analysis_router",
    "router",
    "spring_adapter_router",
]
