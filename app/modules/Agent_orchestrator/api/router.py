"""Agent orchestrator FastAPI 라우터."""
from __future__ import annotations

import os

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ..job_store import JobNotFoundError, job_store
from ..runner import run_job
from ..schemas import AgentJobRecord, AgentJobRequest

router = APIRouter(prefix="/api/agent", tags=["agent-orchestrator"])


@router.get("/health")
async def health() -> dict[str, str]:
    """오케스트레이터 라우터 연결 상태를 확인한다."""
    return {
        "status": "ok",
        "service": "agent-orchestrator",
        "job_store": job_store.__class__.__name__,
        "executor": _executor_mode(),
    }


@router.post("/jobs", response_model=AgentJobRecord, status_code=202)
async def create_job(
    request: AgentJobRequest,
    background_tasks: BackgroundTasks,
) -> AgentJobRecord:
    """AI 모듈 job을 생성하고 백그라운드 실행을 예약한다."""
    record = job_store.create(request)
    if request.run_inline:
        await run_job(record.job_id, request)
    elif _executor_mode() == "celery":
        from ..tasks import run_agent_job_task

        run_agent_job_task.delay(record.job_id, request.model_dump(mode="json"))
    else:
        background_tasks.add_task(run_job, record.job_id, request)
    return job_store.get(record.job_id)


@router.get("/jobs/{job_id}", response_model=AgentJobRecord)
async def get_job(job_id: str) -> AgentJobRecord:
    """job 상태를 조회한다."""
    try:
        return job_store.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job을 찾을 수 없습니다.") from exc


@router.get("/jobs/{job_id}/result")
async def get_job_result(job_id: str) -> dict | list:
    """완료된 job 결과만 반환한다."""
    try:
        record = job_store.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job을 찾을 수 없습니다.") from exc
    if record.status != "done" or record.result is None:
        raise HTTPException(status_code=409, detail=f"job이 완료되지 않았습니다: {record.status}")
    return record.result


def _executor_mode() -> str:
    """job 실행 방식을 반환한다."""
    return os.environ.get("AGENT_JOB_EXECUTOR", "background").strip().lower()
