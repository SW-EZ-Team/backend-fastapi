from __future__ import annotations

import asyncio

from app.modules.ChapterStudio_V1.ai_connectors.base import TTSConnector
from app.modules.ChapterStudio_V1.ai_connectors.registry import get_tts_connector
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.state import StateRecord, StateRecords


async def synthesize_voice_audio(
    voice_scripts: StateRecords,
    connector: TTSConnector | None = None,
    *,
    voice: str = "f1",
    max_concurrency: int = 4,
) -> StateRecords:
    """슬라이드별 음성대본을 TTS 오디오 파일 레코드로 변환한다."""
    if max_concurrency < 1:
        raise ConversionError("max_concurrency는 1 이상이어야 한다.")
    tts = connector or get_tts_connector()
    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = [_synthesize_one(record, tts, voice, semaphore) for record in voice_scripts]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda record: _record_int(record, "slide_idx"))


async def _synthesize_one(
    record: StateRecord,
    connector: TTSConnector,
    voice: str,
    semaphore: asyncio.Semaphore,
) -> StateRecord:
    slide_idx = _record_int(record, "slide_idx")
    script_text = _record_text(record, "script_text")
    async with semaphore:
        payload = await connector.synthesize(script_text, voice=voice)
    audio_url = payload.get("audio_url")
    duration_sec = payload.get("duration_sec")
    if not isinstance(audio_url, str) or audio_url == "":
        raise ConversionError("TTS 결과 audio_url 문자열이 필요하다.")
    if not isinstance(duration_sec, int | float) or duration_sec <= 0:
        raise ConversionError("TTS 결과 duration_sec 양수가 필요하다.")
    return {
        "slide_idx": slide_idx,
        "script_text": script_text,
        "audio_url": audio_url,
        "duration_hint_sec": float(duration_sec),
        "voice": voice,
    }


def _record_text(record: StateRecord, key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or value == "":
        raise ConversionError(f"{key} 문자열이 필요하다.")
    return value


def _record_int(record: StateRecord, key: str) -> int:
    value = record.get(key)
    if not isinstance(value, int):
        raise ConversionError(f"{key} 정수가 필요하다.")
    return value


__all__ = ["synthesize_voice_audio"]
