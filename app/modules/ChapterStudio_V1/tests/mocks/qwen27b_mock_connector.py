from __future__ import annotations

import asyncio

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse


class Qwen27BMockConnector:
    name = "qwen27b_mock"

    def __init__(self, default_text: str = "<section>모의 슬라이드</section>") -> None:
        self.default_text = default_text
        self.calls = 0

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        self.calls += 1
        return ChapterAIResponse(
            text=self.default_text,
            model=self.name,
            input_tokens=len(req.user),
            output_tokens=len(self.default_text),
            finish_reason="stop",
        )

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        return list(await asyncio.gather(*[self.generate(req) for req in reqs]))

    def supports(self, feature: str) -> bool:
        return feature in {"batch"}
