from __future__ import annotations

from pathlib import Path

import pytest

from ai_connectors.tts_schemas import TTSRequest, TTSResponse
from app.modules.ChapterStudio_V1.pipeline import voice_audio
from app.modules.ChapterStudio_V1.pipeline.tts_routing import TutorVoiceProfile, resolve_tts_plan


class FakeRootTTSConnector:
    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.requests: list[TTSRequest] = []

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("modal-offline")
        return TTSResponse(
            audio_bytes=b"RIFFfakeWAVE",
            sample_rate=24000,
            content_type="audio/wav",
            duration_sec=1.25,
            latency_ms=10.0,
            char_count=len(request.text),
            model=self.name,
        )

    def supports(self, feature: str) -> bool:
        return feature in {"tts", "voice_cloning"}


def test_resolve_tts_plan_routes_preset_and_custom_refs() -> None:
    bear = resolve_tts_plan(_profile("tut_0000000000000PRESET_BEAR01"))
    cat = resolve_tts_plan(_profile("tut_00000000000000PRESET_CAT01"))
    custom = resolve_tts_plan(_profile("custom-1", voice_sample_url="https://cdn.local/ref.wav"))

    assert bear.engine == "qwen3-tts-modal"
    assert bear.ref_source.endswith("preset_voice1.wav")
    assert Path(bear.ref_source).is_file()
    assert cat.engine == "qwen3-tts-modal"
    assert cat.ref_source.endswith("preset_voice2.wav")
    assert Path(cat.ref_source).is_file()
    assert custom.engine == "qwen3-tts-modal"
    assert custom.ref_source == "https://cdn.local/ref.wav"


def test_resolve_tts_plan_routes_unvoiced_default_to_gemini_style() -> None:
    formal = resolve_tts_plan(_profile("tut_00000000000000PRESET_OWL01", formal=True))
    casual = resolve_tts_plan(_profile("custom-2", formal=False))

    assert formal.engine == "gemini-tts"
    assert formal.style == "존댓말 과외톤"
    assert casual.engine == "gemini-tts"
    assert casual.style == "반말 친근 과외톤"


@pytest.mark.asyncio
async def test_synthesize_voice_audio_uses_qwen_preset_without_modal_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connector = FakeRootTTSConnector("qwen3-tts-modal")
    requested_names: list[str] = []

    def fake_get_connector(name: str) -> FakeRootTTSConnector:
        requested_names.append(name)
        return connector

    monkeypatch.setattr(voice_audio, "get_root_tts_connector", fake_get_connector)
    monkeypatch.setattr(voice_audio, "tts_output_dir", lambda: tmp_path)

    result = await voice_audio.synthesize_voice_audio(
        [{"slide_idx": 0, "script_text": "곰 선생님 대본입니다."}],
        tutor_profile=_profile("tut_0000000000000PRESET_BEAR01"),
    )

    assert requested_names == ["qwen3-tts-modal"]
    assert connector.requests[0].ref_audio_bytes.startswith(b"RIFF")
    assert result[0]["voice"] == "qwen3-tts-modal"
    assert str(result[0]["audio_url"]).startswith("file://")
    assert len(list(tmp_path.glob("*.wav"))) == 1


@pytest.mark.asyncio
async def test_synthesize_voice_audio_falls_back_to_gemini_when_qwen_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    qwen = FakeRootTTSConnector("qwen3-tts-modal", fail=True)
    gemini = FakeRootTTSConnector("gemini-tts")
    requested_names: list[str] = []

    def fake_get_connector(name: str) -> FakeRootTTSConnector:
        requested_names.append(name)
        return qwen if name == "qwen3-tts-modal" else gemini

    monkeypatch.setattr(voice_audio, "get_root_tts_connector", fake_get_connector)
    monkeypatch.setattr(voice_audio, "tts_output_dir", lambda: tmp_path)

    result = await voice_audio.synthesize_voice_audio(
        [{"slide_idx": 0, "script_text": "폴백 대본입니다."}],
        tutor_profile=_profile("tut_00000000000000PRESET_CAT01", formal=False),
    )

    assert requested_names == ["qwen3-tts-modal", "gemini-tts"]
    assert gemini.requests[0].style == "반말 친근 과외톤"
    assert result[0]["voice"] == "gemini-tts"


def _profile(tutor_id: str, *, formal: bool = True, voice_sample_url: str = "") -> TutorVoiceProfile:
    return TutorVoiceProfile(
        tutor_id=tutor_id,
        is_default_tutor=tutor_id.startswith("tut_"),
        voice_sample_url=voice_sample_url,
        use_formal_speech=formal,
        tutor_tagline="테스트 튜터",
    )
