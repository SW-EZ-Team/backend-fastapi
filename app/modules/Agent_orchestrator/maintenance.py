"""Agent job 유지보수 주기 태스크."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app

from .job_store import job_store
from .callback import post_agent_callback

logger = logging.getLogger(__name__)

# 상수: 타임아웃 기준값
_STALE_THRESHOLD_MIN: int = 30
_PURGE_THRESHOLD_HOURS: int = 24
_MAX_CALLBACK_ATTEMPTS: int = 3


def _utc_now() -> datetime:
    """timezone-aware UTC 현재 시각을 반환한다."""
    return datetime.now(timezone.utc)


@celery_app.task(name="agent_orchestrator.cleanup_stale_jobs")
def cleanup_stale_jobs() -> None:
    """30분 이상 running 상태로 멈춘 job을 error로 전환한다.

    updated_at 기준으로 _STALE_THRESHOLD_MIN 분이 경과한 running job을
    STALE_TIMEOUT 오류 코드와 함께 error 상태로 변경한다.
    """
    cutoff: datetime = _utc_now() - timedelta(minutes=_STALE_THRESHOLD_MIN)
    stale_ids: list[str] = job_store.iter_by_status("running", before=cutoff)

    for job_id in stale_ids:
        job_store.update(
            job_id,
            status="error",
            error_code="STALE_TIMEOUT",
            error_message="30분 초과 응답 없음",
        )
        logger.warning("[maintenance] stale job 처리: job_id=%s", job_id)

    logger.info("[maintenance] cleanup_stale_jobs 완료: %d건 처리", len(stale_ids))


@celery_app.task(name="agent_orchestrator.purge_old_completed_jobs")
def purge_old_completed_jobs() -> None:
    """24시간 이상 경과한 done/error job을 메모리에서 삭제한다.

    updated_at 기준으로 _PURGE_THRESHOLD_HOURS 시간이 지난 완료 job을
    job_store에서 제거하고 삭제 건수를 로그로 기록한다.
    """
    cutoff: datetime = _utc_now() - timedelta(hours=_PURGE_THRESHOLD_HOURS)
    count = job_store.purge_before(("done", "error"), cutoff)
    logger.info("[maintenance] purge_old_completed_jobs 완료: %d건 삭제", count)


@celery_app.task(name="agent_orchestrator.retry_failed_callbacks")
def retry_failed_callbacks() -> None:
    """callback 전송에 실패했고 시도 횟수가 부족한 job을 재시도한다.

    callback_status=="failed" 이고 callback_attempts < _MAX_CALLBACK_ATTEMPTS 인
    job에 대해 post_agent_callback을 호출해 Spring으로 재전송한다.
    """
    retry_ids: list[str] = job_store.iter_by_callback_status(
        "failed", _MAX_CALLBACK_ATTEMPTS,
    )

    for job_id in retry_ids:
        try:
            record = job_store.get(job_id)
            success, attempts, error = asyncio.run(post_agent_callback(record))
            new_status = "sent" if success else "failed"
            job_store.update(
                job_id,
                callback_status=new_status,
                callback_attempts=record.callback_attempts + attempts,
                callback_error=error,
            )
            logger.info(
                "[maintenance] callback 재시도: job_id=%s, 결과=%s",
                job_id,
                new_status,
            )
        except Exception as exc:
            logger.error("[maintenance] callback 재시도 오류: job_id=%s, 오류=%s", job_id, exc)

    logger.info("[maintenance] retry_failed_callbacks 완료: %d건 시도", len(retry_ids))
