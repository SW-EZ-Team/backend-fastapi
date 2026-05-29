"""Celery task entrypoint for Agent orchestrator."""
from __future__ import annotations

import asyncio

from app.celery_app import celery_app

from .runner import run_job
from .schemas import AgentJobRequest


@celery_app.task(name="agent_orchestrator.run_job")
def run_agent_job_task(job_id: str, request_payload: dict) -> None:
    """Celery worker에서 agent job을 실행한다."""
    request = AgentJobRequest.model_validate(request_payload)
    asyncio.run(run_job(job_id, request))
