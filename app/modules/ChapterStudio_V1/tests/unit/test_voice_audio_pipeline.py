from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.voice_audio import synthesize_voice_audio
from app.modules.ChapterStudio_V1.tests.mocks.tts_v1_mock_connector import TTSV1MockConnector


@pytest.mark.asyncio
async def test_synthesize_voice_audio_returns_slide_audio_records() -> None:
    connector = TTSV1MockConnector()

    result = await synthesize_voice_audio(
        [
            {"slide_idx": 1, "script_text": "두 번째 대본입니다."},
            {"slide_idx": 0, "script_text": "첫 번째 대본입니다."},
        ],
        connector,
        voice="teacher-a",
        max_concurrency=2,
    )

    assert [item["slide_idx"] for item in result] == [0, 1]
    assert result[0]["audio_url"].startswith("mock://audio/")
    assert result[0]["duration_hint_sec"] > 0
    assert result[0]["voice"] == "teacher-a"
    assert connector.calls == 2


@pytest.mark.asyncio
async def test_synthesize_voice_audio_rejects_bad_script_record() -> None:
    connector = TTSV1MockConnector()

    with pytest.raises(ConversionError):
        await synthesize_voice_audio([{"slide_idx": 0}], connector)


@pytest.mark.asyncio
async def test_synthesize_voice_audio_rejects_zero_concurrency() -> None:
    connector = TTSV1MockConnector()

    with pytest.raises(ConversionError):
        await synthesize_voice_audio(
            [{"slide_idx": 0, "script_text": "대본입니다."}],
            connector,
            max_concurrency=0,
        )
