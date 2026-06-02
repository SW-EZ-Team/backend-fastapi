from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ai_connectors.tts_schemas import TTSRequest, TTSResponse
from app.modules.ChapterStudio_V1.pipeline import voice_audio
from app.modules.ChapterStudio_V1.pipeline import tts_routing as tts_routing_module
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


class FakeLegacyTTSConnector:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def synthesize(self, text: str, voice: str = "f1") -> dict[str, object]:
        self.texts.append(text)
        return {"audio_url": f"mock://audio/{voice}", "duration_sec": 1.0}


class SlowLegacyTTSConnector:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def synthesize(self, text: str, voice: str = "f1") -> dict[str, object]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        return {"audio_url": f"mock://audio/{text}", "duration_sec": 1.0}


def test_resolve_tts_plan_routes_cat_preset_custom_and_removed_bear() -> None:
    cat = resolve_tts_plan(_profile("tut_00000000000000PRESET_CAT01"))
    bear = resolve_tts_plan(_profile("tut_0000000000000PRESET_BEAR01"))
    custom = resolve_tts_plan(_profile("custom-1", voice_sample_url="https://cdn.local/ref.wav"))

    assert set(tts_routing_module._PRESET_VOICES) == {"tut_00000000000000PRESET_CAT01"}
    assert cat.engine == "qwen3-tts-modal"
    assert cat.ref_source.endswith("preset_voice2.wav")
    assert Path(cat.ref_source).is_file()
    assert bear.engine == "gemini-tts"
    assert bear.ref_source == ""
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
async def test_synthesize_voice_audio_uses_cat_preset_without_modal_call(
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
        [{"slide_idx": 0, "script_text": "냥 튜터 대본입니다."}],
        tutor_profile=_profile("tut_00000000000000PRESET_CAT01"),
    )

    assert requested_names == ["qwen3-tts-modal"]
    assert connector.requests[0].ref_audio_bytes.startswith(b"RIFF")
    assert result[0]["voice"] == "qwen3-tts-modal"
    assert str(result[0]["audio_url"]).startswith("/media/tts/")
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


@pytest.mark.asyncio
async def test_synthesize_voice_audio_uploads_to_s3_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeRootTTSConnector("gemini-tts")
    uploaded: list[dict[str, object]] = []

    def fake_get_connector(name: str) -> FakeRootTTSConnector:
        assert name == "gemini-tts"
        return connector

    async def fake_put_object(data: bytes, key: str, content_type: str) -> str:
        uploaded.append({"data": data, "key": key, "content_type": content_type})
        return f"https://cdn.example/{key}"

    monkeypatch.setattr(voice_audio, "get_root_tts_connector", fake_get_connector)
    monkeypatch.setattr(voice_audio, "s3_enabled", lambda: True)
    monkeypatch.setattr(voice_audio, "put_object", fake_put_object)

    result = await voice_audio.synthesize_voice_audio(
        [{"slide_idx": 3, "script_text": "S3 업로드 대본입니다."}],
        tutor_profile=_profile("custom-2", formal=False),
    )

    assert str(uploaded[0]["key"]).startswith("tts/")
    assert str(uploaded[0]["key"]).endswith(".wav")
    assert uploaded[0]["content_type"] == "audio/wav"
    assert result[0]["audio_url"] == f"https://cdn.example/{uploaded[0]['key']}"


@pytest.mark.asyncio
async def test_synthesize_voice_audio_keeps_original_when_selective_tilde_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeLegacyTTSConnector()
    source = "안녕하세요. 오른쪽이 더 커요. 천천히 따라와 보세요."
    monkeypatch.setattr(voice_audio, "tts_selective_tilde_enabled", lambda: False)

    result = await voice_audio.synthesize_voice_audio(
        [{"slide_idx": 0, "script_text": source}],
        connector=connector,
    )

    assert connector.texts == [source]
    assert result[0]["script_text"] == source


@pytest.mark.asyncio
async def test_synthesize_voice_audio_uses_selective_tilde_for_routed_tts_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connector = FakeRootTTSConnector("qwen3-tts-modal")
    source = "안녕하세요. 오른쪽이 더 커요. 천천히 따라와 보세요."

    def fake_get_connector(name: str) -> FakeRootTTSConnector:
        assert name == "qwen3-tts-modal"
        return connector

    monkeypatch.setattr(voice_audio, "get_root_tts_connector", fake_get_connector)
    monkeypatch.setattr(voice_audio, "tts_output_dir", lambda: tmp_path)
    monkeypatch.setattr(voice_audio, "tts_selective_tilde_enabled", lambda: True)

    result = await voice_audio.synthesize_voice_audio(
        [{"slide_idx": 0, "script_text": source}],
        tutor_profile=_profile("tut_00000000000000PRESET_CAT01"),
    )

    expected = "안녕하세요~ 오른쪽이 더 커요. 천천히 따라와 보세요~"
    assert connector.requests[0].text == expected
    assert result[0]["script_text"] == source


@pytest.mark.asyncio
async def test_synthesize_voice_audio_reads_tts_synth_concurrency_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = SlowLegacyTTSConnector()
    monkeypatch.setenv("TTS_SYNTH_CONCURRENCY", "2")
    monkeypatch.setattr(voice_audio, "tts_selective_tilde_enabled", lambda: False)

    result = await voice_audio.synthesize_voice_audio(
        [
            {"slide_idx": 0, "script_text": "0번 대본"},
            {"slide_idx": 1, "script_text": "1번 대본"},
            {"slide_idx": 2, "script_text": "2번 대본"},
        ],
        connector=connector,
    )

    assert [record["slide_idx"] for record in result] == [0, 1, 2]
    assert connector.max_active == 2


def _profile(tutor_id: str, *, formal: bool = True, voice_sample_url: str = "") -> TutorVoiceProfile:
    return TutorVoiceProfile(
        tutor_id=tutor_id,
        is_default_tutor=tutor_id.startswith("tut_"),
        voice_sample_url=voice_sample_url,
        use_formal_speech=formal,
        tutor_tagline="테스트 튜터",
    )
