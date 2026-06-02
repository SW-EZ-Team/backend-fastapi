from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.modules.ChapterStudio_V1.ai_connectors import tts_audio_storage as storage_module
from app.modules.ChapterStudio_V1.ai_connectors import tts_v2_connector as tts_module


def _install_ref(monkeypatch: pytest.MonkeyPatch, ref_audio: Path) -> None:
    monkeypatch.setattr(tts_module, "tts_ref_audio_path", lambda: ref_audio)
    monkeypatch.setattr(tts_module, "tts_ref_text", lambda: "기준 음성 문장입니다.")
    monkeypatch.setattr(tts_module, "postfx_pipeline", lambda audio, sample_rate: audio)


@pytest.mark.asyncio
async def test_tts_v2_saves_wav_and_returns_media_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ref_audio = tmp_path / "ref.wav"
    out_dir = tmp_path / "out"
    ref_audio.write_bytes(b"RIFF....WAVE")
    _install_ref(monkeypatch, ref_audio)
    monkeypatch.setattr(storage_module, "s3_enabled", lambda: False)
    monkeypatch.setattr(storage_module, "tts_output_dir", lambda: out_dir)
    monkeypatch.setattr(storage_module, "tts_media_url", lambda filename: f"/media/tts/{filename}")

    conn = tts_module.TTSV2Connector()
    monkeypatch.setattr(conn, "_run_synthesis", lambda text: (np.array([0.0, 0.2, -0.2], dtype=np.float32), 24000))

    result = await conn.synthesize("합성할 대본입니다.", voice="teacher-a")

    assert str(result["audio_url"]).startswith("/media/tts/")
    assert not str(result["audio_url"]).startswith("file://")
    assert result["duration_sec"] > 0
    assert len(list(out_dir.glob("*.wav"))) == 1


@pytest.mark.asyncio
async def test_tts_v2_uploads_to_s3_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"RIFF....WAVE")
    uploaded: list[dict[str, object]] = []
    _install_ref(monkeypatch, ref_audio)
    monkeypatch.setattr(storage_module, "s3_enabled", lambda: True)

    async def fake_put_object(data: bytes, key: str, content_type: str) -> str:
        uploaded.append({"data": data, "key": key, "content_type": content_type})
        return f"https://cdn.example/{key}"

    monkeypatch.setattr(storage_module, "put_object", fake_put_object)
    conn = tts_module.TTSV2Connector()
    monkeypatch.setattr(conn, "_run_synthesis", lambda text: (np.array([0.0, 0.2], dtype=np.float32), 24000))

    result = await conn.synthesize("합성할 대본입니다.", voice="teacher-a")

    assert str(uploaded[0]["key"]).startswith("tts/")
    assert str(uploaded[0]["key"]).endswith(".wav")
    assert uploaded[0]["content_type"] == "audio/wav"
    assert result["audio_url"] == f"https://cdn.example/{uploaded[0]['key']}"
    assert not str(result["audio_url"]).startswith("file://")
