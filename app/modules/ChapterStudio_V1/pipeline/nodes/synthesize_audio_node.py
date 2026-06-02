from __future__ import annotations

import logging
from typing import cast

from app.modules.ChapterStudio_V1.common.config import tts_autogen_enabled
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState, StateRecords
from app.modules.ChapterStudio_V1.pipeline.tts_routing import TutorVoiceProfile
from app.modules.ChapterStudio_V1.pipeline.voice_audio import synthesize_voice_audio

_LOG = logging.getLogger(__name__)


async def synthesize_audio_node(state: ChapterStudioState) -> dict[str, StateRecords]:
    """검증 완료된 음성대본을 슬라이드별 오디오 URL로 변환한다."""
    if not tts_autogen_enabled():
        return {}
    try:
        voice_scripts = _records(state, "voice_scripts")
        profile = _profile_from_state(state)
        results = await synthesize_voice_audio(voice_scripts, tutor_profile=profile)
        return {"voice_audio_files": results}
    except Exception as exc:
        _LOG.warning("[chapterstudio] 튜터 음성 자동생성 실패 — audio 없이 저장합니다. error=%s", exc)
        return {"voice_audio_files": []}


def _profile_from_state(state: ChapterStudioState) -> TutorVoiceProfile:
    """그래프 state에 저장된 튜터 설정을 TTS 라우팅 프로필로 축약한다."""
    return TutorVoiceProfile(
        tutor_id=_optional_text(state, "tutor_id"),
        is_default_tutor=_optional_bool(state, "is_default_tutor", True),
        voice_sample_url=_optional_text(state, "voice_sample_url"),
        use_formal_speech=_optional_bool(state, "use_formal_speech", True),
        tutor_tagline=_optional_text(state, "tutor_tagline"),
    )


def _records(state: ChapterStudioState, key: str) -> StateRecords:
    value = state.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ConversionError(f"{key} 목록이 필요하다.")
    return cast(StateRecords, value)


def _optional_text(state: ChapterStudioState, key: str) -> str:
    value = state.get(key)
    return value if isinstance(value, str) else ""


def _optional_bool(state: ChapterStudioState, key: str, default: bool) -> bool:
    value = state.get(key)
    return value if isinstance(value, bool) else default


__all__ = ["synthesize_audio_node"]
