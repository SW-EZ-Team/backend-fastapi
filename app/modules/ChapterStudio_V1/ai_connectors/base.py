from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse


@runtime_checkable
class AIConnector(Protocol):
    name: str

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        ...

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        ...

    def supports(self, feature: str) -> bool:
        ...


@runtime_checkable
class TTSConnector(Protocol):
    name: str

    async def synthesize(
        self, text: str, voice: str = "f1"
    ) -> dict[str, str | float]:
        ...
