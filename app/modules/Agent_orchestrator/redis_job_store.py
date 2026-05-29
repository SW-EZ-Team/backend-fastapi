"""Redis 기반 job store 구현체.

운영 컨테이너에서 AGENT_JOB_STORE=redis 로 선택한다.
InMemoryJobStore 의 CRUD·스캔 메서드를 모두 Redis I/O로 오버라이드한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .job_store import InMemoryJobStore, JobNotFoundError
from .schemas import (
    AgentCallbackStatus,
    AgentJobRecord,
    AgentJobRequest,
    AgentJobStatus,
    utc_now,
)


class RedisJobStore(InMemoryJobStore):
    """Redis 기반 job store.

    테스트 환경에서 Redis가 없으면 사용하지 않는다. 운영 컨테이너에서만
    AGENT_JOB_STORE=redis 로 선택한다.
    """

    def __init__(self, redis_url: str, prefix: str = "agent_job") -> None:
        super().__init__()
        import redis

        self._prefix = prefix
        self._redis = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        self._redis.ping()

    # ── CRUD ───────────────────────────────────────────────

    def create(self, request: AgentJobRequest) -> AgentJobRecord:
        """Redis에 job을 생성한다. idempotency key가 있으면 기존 job을 반환한다."""
        if request.idempotency_key is not None:
            existing_id = self._redis.get(self._idem_key(request.idempotency_key))
            if existing_id:
                return self.get(existing_id)
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
        self._redis.set(self._job_key(record.job_id), record.model_dump_json())
        if record.idempotency_key is not None:
            self._redis.set(self._idem_key(record.idempotency_key), record.job_id)
        return record

    def get(self, job_id: str) -> AgentJobRecord:
        """Redis에서 job 레코드를 조회한다."""
        raw = self._redis.get(self._job_key(job_id))
        if raw is None:
            raise JobNotFoundError(job_id)
        return AgentJobRecord.model_validate_json(raw)

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
        """Redis job 상태를 갱신한다."""
        updated = super().update(
            job_id,
            status=status,
            progress=progress,
            current_stage=current_stage,
            result=result,
            error_code=error_code,
            error_message=error_message,
            callback_status=callback_status,
            callback_attempts=callback_attempts,
            callback_error=callback_error,
            callback_last_at=callback_last_at,
        )
        self._redis.set(self._job_key(job_id), updated.model_dump_json())
        return updated

    # ── 키 헬퍼 ─────────────────────────────────────────────

    def _job_key(self, job_id: str) -> str:
        """Redis job key."""
        return f"{self._prefix}:record:{job_id}"

    def _idem_key(self, idempotency_key: str) -> str:
        """Redis idempotency key."""
        return f"{self._prefix}:idempotency:{idempotency_key}"

    # ── 스캔·퍼지 오버라이드 ──────────────────────────────────

    def _scan_records(self) -> list[AgentJobRecord]:
        """Redis SCAN으로 모든 job 레코드를 순회한다."""
        records: list[AgentJobRecord] = []
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(
                cursor, match=f"{self._prefix}:record:*", count=100,
            )
            for key in keys:
                raw = self._redis.get(key)
                if raw is None:
                    continue
                records.append(AgentJobRecord.model_validate_json(raw))
            if cursor == 0:
                break
        return records

    def iter_by_status(
        self, status: AgentJobStatus, before: datetime | None = None,
    ) -> list[str]:
        """Redis에서 지정 상태의 job ID 목록을 반환한다."""
        return [
            r.job_id for r in self._scan_records()
            if r.status == status and (before is None or r.updated_at < before)
        ]

    def iter_by_callback_status(self, cb_status: str, max_attempts: int) -> list[str]:
        """Redis에서 콜백 상태별 job ID 목록을 반환한다."""
        return [
            r.job_id for r in self._scan_records()
            if r.callback_status == cb_status and r.callback_attempts < max_attempts
        ]

    def purge_before(self, statuses: tuple[str, ...], cutoff: datetime) -> int:
        """Redis에서 지정 상태이고 cutoff 이전의 job을 삭제한다."""
        count = 0
        for record in self._scan_records():
            if record.status in statuses and record.updated_at < cutoff:
                self._redis.delete(self._job_key(record.job_id))
                if record.idempotency_key is not None:
                    self._redis.delete(self._idem_key(record.idempotency_key))
                count += 1
        return count
