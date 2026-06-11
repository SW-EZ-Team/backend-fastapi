"""도메인 공용 폴백 래퍼.

주(primary) 커넥터를 먼저 호출하고, ConnectorError 계열 예외가 나면 대체(fallback)
커넥터로 한 번 재시도한다. 텍스트(generate/generate_batch), OCR(recognize),
ASR(generate), TTS(synthesize) 가 메서드 이름만 다르고 폴백 로직은 동일하므로,
호출 메서드 이름을 파라미터로 받아 한 클래스로 처리한다.

ChapterStudio_V1 의 FailoverAIConnector(연속 실패 N회 후 회로 고정)와 달리, 이 래퍼는
매 호출마다 primary 를 먼저 시도한다(Gemini 가 회복되면 자동으로 primary 로 복귀).
텍스트 도메인은 기존 FailoverAIConnector 를 그대로 재사용하므로 이 래퍼를 쓰지 않는다.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .errors import AIConnectorError


class DomainFailoverConnector:
    """primary 호출 실패 시 fallback 으로 넘기는 단순 폴백 래퍼."""

    def __init__(
        self,
        primary: Any,
        fallback_factory: Callable[[], Any],
        *,
        method_name: str,
        name: str,
    ) -> None:
        self._primary = primary
        self._fallback_factory = fallback_factory
        self._fallback: Any | None = None
        self._method_name = method_name
        self.name = name

    async def _call(self, request: object) -> object:
        """primary 를 먼저 호출하고, ConnectorError 계열이면 fallback 으로 재시도한다."""
        primary_method: Callable[[object], Awaitable[object]] = getattr(
            self._primary, self._method_name
        )
        try:
            return await primary_method(request)
        except AIConnectorError:
            fallback_method: Callable[[object], Awaitable[object]] = getattr(
                self._fallback_connector(), self._method_name
            )
            return await fallback_method(request)

    def _fallback_connector(self) -> Any:
        """fallback 커넥터를 지연 생성한다(실제 폴백이 일어날 때만 인스턴스화)."""
        if self._fallback is None:
            self._fallback = self._fallback_factory()
        return self._fallback

    def supports(self, feature: str) -> bool:
        """fallback 사실 자체와 primary capability 를 함께 노출한다."""
        if feature == "fallback":
            return True
        return self._primary.supports(feature)


class FailoverOCRConnector(DomainFailoverConnector):
    """OCR 폴백 래퍼 — recognize(req) 를 위임한다."""

    def __init__(self, primary: Any, fallback_factory: Callable[[], Any]) -> None:
        super().__init__(
            primary,
            fallback_factory,
            method_name="recognize",
            name="ocr-failover",
        )

    async def recognize(self, req: object) -> object:
        return await self._call(req)


class FailoverASRConnector(DomainFailoverConnector):
    """ASR 폴백 래퍼 — generate(req) 를 위임한다."""

    def __init__(self, primary: Any, fallback_factory: Callable[[], Any]) -> None:
        super().__init__(
            primary,
            fallback_factory,
            method_name="generate",
            name="asr-failover",
        )

    async def generate(self, request: object) -> object:
        return await self._call(request)


class FailoverTTSConnector(DomainFailoverConnector):
    """TTS 폴백 래퍼 — synthesize(req) 를 위임한다."""

    def __init__(self, primary: Any, fallback_factory: Callable[[], Any]) -> None:
        super().__init__(
            primary,
            fallback_factory,
            method_name="synthesize",
            name="tts-failover",
        )

    async def synthesize(self, request: object) -> object:
        return await self._call(request)
