from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from time import time
from uuid import uuid4

import httpx
from ai_connectors.registry import get_tts_connector as get_root_tts_connector
from ai_connectors.tts_schemas import TTSRequest, TTSResponse

from app.modules.ChapterStudio_V1.ai_connectors.base import TTSConnector
from app.modules.ChapterStudio_V1.ai_connectors.registry import get_tts_connector
from app.modules.ChapterStudio_V1.common.config import tts_output_dir
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.state import StateRecord, StateRecords
from app.modules.ChapterStudio_V1.pipeline.tts_routing import TutorVoiceProfile, TtsPlan, resolve_tts_plan

_LOG = logging.getLogger(__name__)
_REF_DOWNLOAD_TIMEOUT_SEC = 10.0


async def synthesize_voice_audio(
    voice_scripts: StateRecords,
    connector: TTSConnector | None = None,
    *,
    voice: str = "f1",
    max_concurrency: int = 4,
    tutor_profile: TutorVoiceProfile | None = None,
) -> StateRecords:
    """슬라이드별 음성대본을 TTS 오디오 파일 레코드로 변환한다."""
    if max_concurrency < 1:
        raise ConversionError("max_concurrency는 1 이상이어야 한다.")
    if tutor_profile is not None:
        return await _synthesize_with_tutor_profile(voice_scripts, tutor_profile, max_concurrency)
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


async def _synthesize_with_tutor_profile(
    voice_scripts: StateRecords,
    tutor_profile: TutorVoiceProfile,
    max_concurrency: int,
) -> StateRecords:
    plan = resolve_tts_plan(tutor_profile)
    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = [_synthesize_one_routed(record, plan, tutor_profile, semaphore) for record in voice_scripts]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda record: _record_int(record, "slide_idx"))


async def _synthesize_one_routed(
    record: StateRecord,
    plan: TtsPlan,
    tutor_profile: TutorVoiceProfile,
    semaphore: asyncio.Semaphore,
) -> StateRecord:
    slide_idx = _record_int(record, "slide_idx")
    script_text = _record_text(record, "script_text")
    async with semaphore:
        try:
            response = await _synthesize_by_plan(script_text, plan)
            used_plan = plan
        except Exception as exc:
            if plan.engine == "gemini-tts":
                raise
            fallback = TtsPlan(engine="gemini-tts", ref_source="", style=_fallback_style(tutor_profile))
            _LOG.warning("튜터 TTS 합성 실패 — gemini-tts로 폴백합니다. engine=%s, error=%s", plan.engine, exc)
            response = await _synthesize_by_plan(script_text, fallback)
            used_plan = fallback
    return {
        "slide_idx": slide_idx,
        "script_text": script_text,
        "audio_url": _save_audio_bytes(response.audio_bytes, slide_idx, used_plan.engine),
        "duration_hint_sec": float(response.duration_sec),
        "voice": used_plan.engine,
    }


async def _synthesize_by_plan(script_text: str, plan: TtsPlan) -> TTSResponse:
    connector = get_root_tts_connector(plan.engine)
    if plan.engine == "qwen3-tts-modal":
        request = TTSRequest(text=script_text, ref_audio_bytes=await _load_ref_audio(plan.ref_source))
        return await connector.synthesize(request)
    request = TTSRequest(text=script_text, ref_audio_bytes=b"", style=plan.style)
    return await connector.synthesize(request)


async def _load_ref_audio(ref_source: str) -> bytes:
    if ref_source.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=_REF_DOWNLOAD_TIMEOUT_SEC) as client:
            response = await client.get(ref_source)
            response.raise_for_status()
            return response.content
    return Path(ref_source).expanduser().read_bytes()


def _save_audio_bytes(audio_bytes: bytes, slide_idx: int, engine: str) -> str:
    output_dir = tts_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{int(time() * 1000)}_{slide_idx}_{_safe_token(engine)}_{uuid4().hex[:8]}.wav"
    path = output_dir / filename
    path.write_bytes(audio_bytes)
    return path.resolve().as_uri()


def _fallback_style(tutor_profile: TutorVoiceProfile) -> str:
    if tutor_profile.use_formal_speech:
        return "존댓말 과외톤"
    return "반말 친근 과외톤"


def _safe_token(value: str) -> str:
    token = "".join(char for char in value if char.isalnum() or char in {"-", "_"})
    return token[:32] or "tts"


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
