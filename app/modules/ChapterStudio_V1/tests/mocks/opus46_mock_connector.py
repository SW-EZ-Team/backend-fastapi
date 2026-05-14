from __future__ import annotations

import asyncio
import json

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse

_MODEL_ID = "claude-opus-4-6-mock"


class Opus46MockConnector:
    name = "opus46_mock"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        self.calls += 1
        outline = [{"slide_idx": idx, "title": f"모의 {idx}", "category": "text"} for idx in range(10)]
        text = json.dumps({"outline": outline}, ensure_ascii=False)
        return ChapterAIResponse(
            text=text,
            model=_MODEL_ID,
            input_tokens=len(req.user),
            output_tokens=len(text),
            finish_reason="stop",
        )

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        return list(await asyncio.gather(*[self.generate(req) for req in reqs]))

    def supports(self, feature: str) -> bool:
        return feature in {"long_context", "json_mode"}
