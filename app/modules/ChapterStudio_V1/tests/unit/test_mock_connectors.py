from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector, TTSConnector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.tests.mocks.opus46_mock_connector import Opus46MockConnector
from app.modules.ChapterStudio_V1.tests.mocks.qwen27b_mock_connector import Qwen27BMockConnector
from app.modules.ChapterStudio_V1.tests.mocks.tts_v1_mock_connector import TTSV1MockConnector


@pytest.mark.asyncio
async def test_qwen_mock_protocol_and_counter() -> None:
    conn = Qwen27BMockConnector()
    assert isinstance(conn, AIConnector)
    await conn.generate(ChapterAIRequest(user="슬라이드", max_tokens=32, temperature=0.2))
    assert conn.calls == 1


@pytest.mark.asyncio
async def test_opus_mock_batch_preserves_count() -> None:
    conn = Opus46MockConnector()
    reqs = [ChapterAIRequest(user="기획", max_tokens=32, temperature=0.2) for _ in range(2)]
    responses = await conn.generate_batch(reqs)
    assert isinstance(conn, AIConnector)
    assert len(responses) == 2
    assert conn.calls == 2


@pytest.mark.asyncio
async def test_tts_mock_protocol_and_duration() -> None:
    conn = TTSV1MockConnector()
    result = await conn.synthesize("가나다")
    assert isinstance(conn, TTSConnector)
    assert result["audio_url"] == "mock://audio/026d8d68"
    assert result["duration_sec"] == 0.15000000000000002
