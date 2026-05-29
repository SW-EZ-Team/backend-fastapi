"""TTS V2 — 오디오북 합성 파이프라인 패키지 루트."""
from __future__ import annotations

from app.modules.TTS_V2.app.routers.tts_v2 import router
from app.modules.TTS_V2.pipeline.graph import get_compiled_graph
from app.modules.TTS_V2.schemas.request import TTSV2TextRequest
from app.modules.TTS_V2.schemas.response import TTSV2Response


async def synthesize_audiobook(
    text: str,
    ref_audio_base64: str | None = None,
    ref_text: str | None = None,
    language: str = "ko",
    speed: float = 1.0,
    voice_profile_id: str | None = None,
) -> TTSV2Response:
    """다른 모듈이 라우터 없이 TTS 파이프라인을 호출할 수 있게 하는 공개 함수."""
    from app.modules.TTS_V2.app.routers.helpers import state_to_response
    from app.modules.TTS_V2.app.routers.helpers_async import resolve_ref_async
    from app.modules.TTS_V2.pipeline.config import TTS_V2_MAX_RETRIES, TTS_V2_QC_ENGINE
    from app.modules.TTS_V2.schemas.state import AudiobookState

    ref_audio_bytes, resolved_ref_text, resolved_profile_id = await resolve_ref_async(
        ref_audio_base64,
        ref_text,
        voice_profile_id,
    )
    initial_state: AudiobookState = {
        "input_type": "text",
        "raw_text": text,
        "file_content": None,
        "ref_audio_bytes": ref_audio_bytes,
        "ref_text": resolved_ref_text,
        "ref_sample_rate": 0,
        "language": language,
        "sections": [],
        "chunks": [],
        "current_phase": "init",
        "max_retries": TTS_V2_MAX_RETRIES,
        "failed_chunks": [],
        "merged_audio_bytes": None,
        "total_duration_sec": 0.0,
        "pipeline_status": "loading",
        "error_message": None,
        "timings": {},
        "skip_planner": False,
        "skip_postfx": False,
        "qc_engine": TTS_V2_QC_ENGINE,
        "voice_profile_id": resolved_profile_id,
        "speed": speed,
    }
    result: AudiobookState = await get_compiled_graph().ainvoke(initial_state)
    return state_to_response(result, TTS_V2_QC_ENGINE)


__all__ = ["TTSV2Response", "TTSV2TextRequest", "router", "synthesize_audiobook"]
