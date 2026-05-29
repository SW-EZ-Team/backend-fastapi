"""Agent orchestrator job store.

기본은 로컬 테스트에 안전한 인메모리 저장소이고, 운영에서는
AGENT_JOB_STORE=redis 로 Redis 저장소를 선택할 수 있다.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from threading import RLock
from typing import Any

_LOG = logging.getLogger(__name__)

from .schemas import (
    AgentCallbackStatus,
    AgentJobRecord,
    AgentJobRequest,
    AgentJobStatus,
    utc_now,
)


class JobNotFoundError(KeyError):
    """요청한 job_id가 없을 때 발생한다."""


class InMemoryJobStore:
    """프로세스 생존 기간 동안 job 상태를 보관하는 작은 저장소."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, AgentJobRecord] = {}

    def create(self, request: AgentJobRequest) -> AgentJobRecord:
        """job 레코드를 queued 상태로 생성한다."""
        if request.idempotency_key is not None:
            existing = self._find_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                return existing
        record = AgentJobRecord(
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            idempotency_key=request.idempotency_key,
            module=request.module,
            action=request.action,
            payload=request.payload,
            callback_url=request.callback_url,
            callback_status="pending" if request.callback_url else "not_requested",
            notify_telegram_chat_id=request.notify_telegram_chat_id,
        )
        with self._lock:
            self._records[record.job_id] = record
        return record

    def _find_by_idempotency_key(self, idempotency_key: str) -> AgentJobRecord | None:
        """동일 idempotency key로 생성된 기존 job을 찾는다."""
        with self._lock:
            for record in self._records.values():
                if record.idempotency_key == idempotency_key:
                    return record
        return None

    def get(self, job_id: str) -> AgentJobRecord:
        """job 레코드를 조회한다."""
        with self._lock:
            record = self._records.get(job_id)
        if record is None:
            raise JobNotFoundError(job_id)
        return record

    def update(
        self,
        job_id: str,
        *,
        status: AgentJobStatus | None = None,
        progress: float | None = None,
        current_stage: str | None = None,
        result: dict[str, Any] | list[Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        callback_status: AgentCallbackStatus | None = None,
        callback_attempts: int | None = None,
        callback_error: str | None = None,
        callback_last_at: object | None = None,
    ) -> AgentJobRecord:
        """job 상태와 결과를 갱신한다."""
        current = self.get(job_id)
        values: dict[str, Any] = {"updated_at": utc_now()}
        if status is not None:
            values["status"] = status
        if progress is not None:
            values["progress"] = progress
        if current_stage is not None:
            values["current_stage"] = current_stage
        if result is not None:
            values["result"] = result
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message
        if callback_status is not None:
            values["callback_status"] = callback_status
        if callback_attempts is not None:
            values["callback_attempts"] = callback_attempts
        if callback_error is not None:
            values["callback_error"] = callback_error
        if callback_last_at is not None:
            values["callback_last_at"] = callback_last_at
        updated = current.model_copy(update=values)
        with self._lock:
            self._records[job_id] = updated
        return updated

    def iter_by_status(
        self, status: AgentJobStatus, before: datetime | None = None,
    ) -> list[str]:
        """지정 상태이고 before 이전에 갱신된 job ID 목록을 반환한다."""
        with self._lock:
            return [
                jid for jid, r in self._records.items()
                if r.status == status and (before is None or r.updated_at < before)
            ]

    def iter_by_callback_status(self, cb_status: str, max_attempts: int) -> list[str]:
        """콜백 상태가 cb_status이고 시도 횟수가 max_attempts 미만인 job ID 목록."""
        with self._lock:
            return [
                jid for jid, r in self._records.items()
                if r.callback_status == cb_status and r.callback_attempts < max_attempts
            ]

    def purge_before(self, statuses: tuple[str, ...], cutoff: datetime) -> int:
        """지정 상태이고 cutoff 이전에 갱신된 job을 삭제하고 삭제 건수를 반환한다."""
        with self._lock:
            to_del = [
                jid for jid, r in self._records.items()
                if r.status in statuses and r.updated_at < cutoff
            ]
            for jid in to_del:
                del self._records[jid]
        return len(to_del)


def create_job_store() -> InMemoryJobStore:
    """환경변수에 따라 job store 구현체를 선택한다."""
    backend = os.environ.get("AGENT_JOB_STORE", "memory").strip().lower()
    if backend != "redis":
        return InMemoryJobStore()
    redis_url = os.environ.get("AGENT_JOB_REDIS_URL") or os.environ.get("REDIS_URL")
    if not redis_url:
        if os.environ.get("AGENT_JOB_STORE_STRICT") == "1":
            raise RuntimeError("AGENT_JOB_STORE=redis 이지만 Redis URL이 없습니다.")
        return InMemoryJobStore()
    try:
        from .redis_job_store import RedisJobStore

        return RedisJobStore(redis_url)
    except Exception:
        _LOG.warning("Redis JobStore 초기화 실패, InMemory 폴백 사용", exc_info=True)
        if os.environ.get("AGENT_JOB_STORE_STRICT") == "1":
            raise
        return InMemoryJobStore()


job_store = create_job_store()
