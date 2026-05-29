from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector
from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse

_T = TypeVar("_T")


class FailoverAIConnector:
    """주 커넥터가 연속 실패하면 대체 커넥터로 회로를 넘긴다."""

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
        self._primary: AIConnector | None = None
        self._fallback: AIConnector | None = None
        self._failure_count = 0
        self._fallback_active = False
        self._last_failure = ""

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
        if self._fallback_active:
            return await self._fallback_connector().generate(req)

        last_error: ConnectorError | None = None
        while not self._fallback_active:
            try:
                response = await self._with_optional_timeout(self._primary_connector().generate(req))
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
        if not reqs:
            return []
        if self._fallback_active:
            return await self._fallback_connector().generate_batch(reqs)

        last_error: ConnectorError | None = None
        while not self._fallback_active:
            try:
                responses = await self._with_optional_timeout(self._primary_connector().generate_batch(reqs))
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
        return self._primary_connector().supports(feature) or self._fallback_connector().supports(feature)

    async def aclose(self) -> None:
        for connector in (self._primary, self._fallback):
            close = getattr(connector, "aclose", None)
            if close is not None:
                await close()

    def _primary_connector(self) -> AIConnector:
        if self._primary is None:
            self._primary = self._primary_factory()
        return self._primary

    def _fallback_connector(self) -> AIConnector:
        if self._fallback is None:
            self._fallback = self._fallback_factory()
        return self._fallback

    async def _with_optional_timeout(self, awaitable: Awaitable[_T]) -> _T:
        if self._primary_timeout_sec is None:
            return await awaitable
        try:
            return await asyncio.wait_for(awaitable, timeout=self._primary_timeout_sec)
        except asyncio.TimeoutError as exc:
            raise ConnectorTimeoutError(f"primary connector {self._primary_timeout_sec:.0f}초 초과") from exc

    def _record_failure(self, exc: ConnectorError, *, count: int) -> None:
        self._failure_count += count
        self._last_failure = str(exc)
        if self._failure_count >= self._failure_threshold:
            self._fallback_active = True
