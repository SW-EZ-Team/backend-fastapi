from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.pipeline.nodes import synthesize_audio_node as node
from app.modules.ChapterStudio_V1.pipeline.tts_routing import TutorVoiceProfile


@pytest.mark.asyncio
async def test_synthesize_audio_node_noops_when_flag_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("TTS 자동생성 비활성 상태에서 호출되면 안 된다.")

    monkeypatch.delenv("TTS_AUTOGEN_ENABLED", raising=False)
    monkeypatch.setattr(node, "synthesize_voice_audio", fail_if_called)

    result = await node.synthesize_audio_node({"voice_scripts": [_script(0)]})

    assert result == {}


@pytest.mark.asyncio
async def test_synthesize_audio_node_fills_voice_audio_files(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_synthesize(
        voice_scripts: list[dict[str, object]],
        *,
        tutor_profile: TutorVoiceProfile,
    ) -> list[dict[str, object]]:
        captured["voice_scripts"] = voice_scripts
        captured["profile"] = tutor_profile
        return [{"slide_idx": 0, "audio_url": "mock://audio/0", "duration_hint_sec": 1.5}]

    monkeypatch.setenv("TTS_AUTOGEN_ENABLED", "1")
    monkeypatch.setattr(node, "synthesize_voice_audio", fake_synthesize)

    result = await node.synthesize_audio_node(
        {
            "voice_scripts": [_script(0)],
            "tutor_id": "tut_00000000000000PRESET_CAT01",
            "is_default_tutor": True,
            "voice_sample_url": "https://cdn.local/ref.wav",
            "use_formal_speech": False,
            "tutor_tagline": "차분한 튜터",
        }
    )

    profile = captured["profile"]
    assert result == {"voice_audio_files": [{"slide_idx": 0, "audio_url": "mock://audio/0", "duration_hint_sec": 1.5}]}
    assert captured["voice_scripts"] == [_script(0)]
    assert isinstance(profile, TutorVoiceProfile)
    assert profile.tutor_id == "tut_00000000000000PRESET_CAT01"
    assert profile.voice_sample_url == "https://cdn.local/ref.wav"
    assert profile.use_formal_speech is False


@pytest.mark.asyncio
async def test_synthesize_audio_node_returns_empty_audio_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_synthesize(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError("modal-blocked")

    monkeypatch.setenv("TTS_AUTOGEN_ENABLED", "1")
    monkeypatch.setattr(node, "synthesize_voice_audio", fail_synthesize)

    result = await node.synthesize_audio_node({"voice_scripts": [_script(0)]})

    assert result == {"voice_audio_files": []}


def _script(slide_idx: int) -> dict[str, object]:
    return {"slide_idx": slide_idx, "script_text": "검증 완료된 튜터 대본입니다."}
