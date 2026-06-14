"""텍스트 생성 폴백 커넥터.

주 커넥터가 연속 failure_threshold 회 실패하면 대체 커넥터로 회로를 전환한다.
전환 후에도 TEXT_FALLBACK_RECOVERY_SEC(기본 60초, 0 이하면 비활성=영구 전환)가
지나면 주 커넥터를 1회 다시 시도해 성공 시 회로를 닫는다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from ai_connectors.base import AIConnector
from ai_connectors.errors import ConnectorError
from ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from ai_connectors.text_schemas import ChapterAIRequest, ChapterAIResponse

_T = TypeVar("_T")

_LOG = logging.getLogger(__name__)

# 주 커넥터 복귀 시도 간격 기본값(초) — 0 이하면 복귀 비활성(영구 폴백)
_DEFAULT_RECOVERY_SEC = 60.0


def _recovery_interval_sec() -> float:
    """TEXT_FALLBACK_RECOVERY_SEC 환경변수를 읽는다(호출 시마다 — 테스트 monkeypatch 가능)."""
    raw = os.getenv("TEXT_FALLBACK_RECOVERY_SEC")
    if raw is None or not raw.strip():
        return _DEFAULT_RECOVERY_SEC
    try:
        return float(raw.strip())
    except ValueError:
        return _DEFAULT_RECOVERY_SEC


class FailoverAIConnector:
    """주 커넥터가 연속 실패하면 대체 커넥터로 회로를 넘긴다.

    failure_threshold 에 도달하는 순간 _fallback_active 가 True 로 전환되고,
    이후 요청은 폴백 커넥터로 라우팅된다. 단 TEXT_FALLBACK_RECOVERY_SEC(기본
    60초, 0 이하면 비활성=기존 영구 전환 동작)가 지나면 다음 요청에서 주
    커넥터를 1회 다시 시도하고, 성공하면 회로를 닫아 주 커넥터로 복귀한다.
    실패하면 다음 복귀 시도를 같은 간격만큼 뒤로 미루고 폴백으로 진행한다
    (ai_connectors/_failover_text.py 와 동일한 복귀 의미론).
    """

    def __init__(
        self,
        primary_factory: Callable[[], AIConnector],
        fallback_factory: Callable[[], AIConnector],
        *,
        name: str,
        failure_threshold: int = 3,
        primary_timeout_sec: float | None = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold는 1 이상이어야 한다.")
        self.name = name
        self._primary_factory = primary_factory
        self._fallback_factory = fallback_factory
        self._failure_threshold = failure_threshold
        self._primary_timeout_sec = primary_timeout_sec
        # 지연 초기화 — 최초 호출 시점에 팩토리 실행
        self._primary: AIConnector | None = None
        self._fallback: AIConnector | None = None
        self._failure_count = 0
        self._fallback_active = False
        self._last_failure = ""
        # 주 커넥터 복귀 시도가 허용되는 monotonic 시각 — 폴백 전환/복귀 실패 시 갱신
        self._primary_retry_at: float | None = None

    @property
    def fallback_active(self) -> bool:
        return self._fallback_active

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def last_failure(self) -> str:
        return self._last_failure

    @property
    def primary_name(self) -> str:
        return self._primary.name if self._primary is not None else "primary"

    @property
    def fallback_name(self) -> str:
        return self._fallback.name if self._fallback is not None else "fallback"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """폴백 활성 시 즉시 대체 커넥터로 위임하고, 아니면 주 커넥터를 시도한다."""
        if self._fallback_active:
            # 복귀 간격이 지났으면 주 커넥터를 1회 다시 시도한다(성공 시 회로 닫힘)
            if self._primary_probe_due():
                recovered = await self._probe_primary(
                    lambda: self._with_optional_timeout(self._primary_connector().generate(req))
                )
                if recovered is not None:
                    return recovered
            return await self._fallback_connector().generate(req)

        last_error: ConnectorError | None = None
        while not self._fallback_active:
            try:
                response = await self._with_optional_timeout(
                    self._primary_connector().generate(req)
                )
                self._failure_count = 0
                self._last_failure = ""
                return response
            except ConnectorError as exc:
                last_error = exc
                self._record_failure(exc, count=1)

        if last_error is not None:
            self._last_failure = str(last_error)
        return await self._fallback_connector().generate(req)

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        """배치도 단일 요청과 동일한 폴백 논리를 따른다."""
        if not reqs:
            return []
        if self._fallback_active:
            # 복귀 간격이 지났으면 주 커넥터를 1회 다시 시도한다(성공 시 회로 닫힘)
            if self._primary_probe_due():
                recovered = await self._probe_primary(
                    lambda: self._with_optional_timeout(
                        self._primary_connector().generate_batch(reqs)
                    )
                )
                if recovered is not None:
                    return recovered
            return await self._fallback_connector().generate_batch(reqs)

        last_error: ConnectorError | None = None
        while not self._fallback_active:
            try:
                responses = await self._with_optional_timeout(
                    self._primary_connector().generate_batch(reqs)
                )
                self._failure_count = 0
                self._last_failure = ""
                return responses
            except ConnectorError as exc:
                last_error = exc
                self._record_failure(exc, count=len(reqs))

        if last_error is not None:
            self._last_failure = str(last_error)
        return await self._fallback_connector().generate_batch(reqs)

    def supports(self, feature: str) -> bool:
        if feature == "fallback":
            return True
        return self._primary_connector().supports(feature) or self._fallback_connector().supports(
            feature
        )

    async def aclose(self) -> None:
        """연결된 모든 커넥터 자원을 정리한다."""
        for connector in (self._primary, self._fallback):
            close = getattr(connector, "aclose", None)
            if close is not None:
                await close()

    # --- 내부 헬퍼 ---

    def _primary_connector(self) -> AIConnector:
        """주 커넥터를 지연 초기화해 반환한다."""
        if self._primary is None:
            self._primary = self._primary_factory()
        return self._primary

    def _fallback_connector(self) -> AIConnector:
        """대체 커넥터를 지연 초기화해 반환한다."""
        if self._fallback is None:
            self._fallback = self._fallback_factory()
        return self._fallback

    async def _with_optional_timeout(self, awaitable: Awaitable[_T]) -> _T:
        """primary_timeout_sec 설정 시 타임아웃을 적용한다."""
        if self._primary_timeout_sec is None:
            return await awaitable
        try:
            return await asyncio.wait_for(awaitable, timeout=self._primary_timeout_sec)
        except asyncio.TimeoutError as exc:
            raise ConnectorTimeoutError(
                f"primary connector {self._primary_timeout_sec:.0f}초 초과"
            ) from exc

    def _record_failure(self, exc: ConnectorError, *, count: int) -> None:
        """실패를 누적하고 임계값 초과 시 폴백으로 전환한다."""
        self._failure_count += count
        self._last_failure = str(exc)
        if self._failure_count >= self._failure_threshold:
            self._fallback_active = True
            self._schedule_primary_probe()

    # ── 주 커넥터 복귀(recovery) ──────────────────────────────────────

    def _schedule_primary_probe(self) -> None:
        """다음 주 커넥터 복귀 시도 시각을 예약한다. 간격이 0 이하면 비활성(영구 폴백)."""
        interval = _recovery_interval_sec()
        self._primary_retry_at = (
            time.monotonic() + interval if interval > 0 else None
        )

    def _primary_probe_due(self) -> bool:
        """주 커넥터 복귀 시도가 가능한 시점인지 확인한다."""
        return (
            self._primary_retry_at is not None
            and time.monotonic() >= self._primary_retry_at
        )

    async def _probe_primary(self, call: Callable[[], Awaitable[_T]]) -> _T | None:
        """폴백 활성 상태에서 주 커넥터를 1회 시도한다.

        성공하면 회로를 닫고(주 커넥터 복귀) 결과를 반환한다.
        실패하면 다음 복귀 시도를 뒤로 미루고 None을 반환해 폴백으로 진행시킨다.
        """
        try:
            result = await call()
        except ConnectorError as exc:
            self._last_failure = str(exc)
            self._schedule_primary_probe()
            _LOG.warning(
                "%s: 주 커넥터 복귀 시도 실패 — 폴백 유지, 다음 시도 예약: %s",
                self.name,
                exc,
            )
            return None
        self._fallback_active = False
        self._failure_count = 0
        self._last_failure = ""
        self._primary_retry_at = None
        _LOG.info("%s: 주 커넥터(%s) 복귀 성공 — 회로 닫힘", self.name, self.primary_name)
        return result
