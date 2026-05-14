from __future__ import annotations

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse


class MockTextConnector:
    """Qwen27B 가짜 응답 — 단위 테스트 전용."""

    name = "mock_text"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        return ChapterAIResponse(
            text="mock text response",
            model="mock_qwen27b",
            input_tokens=10,
            output_tokens=5,
            finish_reason="stop",
        )

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        return [await self.generate(r) for r in reqs]

    def supports(self, feature: str) -> bool:
        return feature in {"batch", "long_context"}


class MockPlannerConnector:
    """Opus46 가짜 응답 — 단위 테스트 전용."""

    name = "mock_planner"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        return ChapterAIResponse(
            text="mock planner response",
            model="mock_opus46",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
        )

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        return [await self.generate(r) for r in reqs]

    def supports(self, feature: str) -> bool:
        return feature in {"long_context", "json_mode"}


class MockTTSConnector:
    """TTS V1 가짜 응답 — 단위 테스트 전용."""

    name = "mock_tts"

    async def synthesize(self, text: str, voice: str = "f1") -> dict[str, str | float]:
        return {"audio_url": "http://mock/audio.mp3", "duration_sec": 3.0}

    def supports(self, feature: str) -> bool:
        return feature in {"tts_synthesis"}
