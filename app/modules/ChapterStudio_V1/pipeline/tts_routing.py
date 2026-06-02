from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_VOICE_ASSET_DIR = Path(__file__).resolve().parents[2] / "TTS_V2" / "assets" / "voices"
_PRESET_VOICES = {
    "tut_00000000000000PRESET_CAT01": "preset_voice2.wav",
}


@dataclass(frozen=True)
class TutorVoiceProfile:
    """튜터 음성 선택에 필요한 최소 프로필이다."""

    tutor_id: str
    is_default_tutor: bool
    voice_sample_url: str
    use_formal_speech: bool
    tutor_tagline: str


@dataclass(frozen=True)
class TtsPlan:
    """TTS 실행 전에 확정된 엔진·참조음성·스타일 계획이다."""

    engine: str
    ref_source: str
    style: str


def resolve_tts_plan(profile: TutorVoiceProfile) -> TtsPlan:
    """튜터 프로필을 실제 TTS 엔진 계획으로 변환한다."""
    preset = _PRESET_VOICES.get(profile.tutor_id)
    if preset is not None:
        return TtsPlan(
            engine="qwen3-tts-modal",
            ref_source=str(_safe_asset_path(preset)),
            style="",
        )
    custom_ref = profile.voice_sample_url.strip()
    if custom_ref:
        return TtsPlan(engine="qwen3-tts-modal", ref_source=custom_ref, style="")
    return TtsPlan(engine="gemini-tts", ref_source="", style=_speech_style(profile.use_formal_speech))


def _speech_style(use_formal_speech: bool) -> str:
    if use_formal_speech:
        return "존댓말 과외톤"
    return "반말 친근 과외톤"


def _safe_asset_path(file_name: str) -> Path:
    """프리셋 파일은 지정된 assets/voices 내부의 실제 파일만 허용한다."""
    base = _VOICE_ASSET_DIR.resolve()
    path = (base / file_name).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ValueError("프리셋 음성 경로가 assets/voices 밖을 가리킨다.") from exc
    if not path.is_file():
        raise FileNotFoundError(f"프리셋 음성 파일을 찾을 수 없다: {path}")
    return path


__all__ = ["TtsPlan", "TutorVoiceProfile", "resolve_tts_plan"]
