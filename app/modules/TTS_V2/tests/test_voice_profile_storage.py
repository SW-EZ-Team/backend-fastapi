from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from common.audio_io import encode_wav_bytes
from app.modules.TTS_V2.services import voice_profile_storage as storage


@pytest.mark.asyncio
async def test_save_audio_uploads_to_s3_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    uploaded: list[dict[str, object]] = []

    async def fake_put_object(data: bytes, key: str, content_type: str) -> str:
        uploaded.append({"data": data, "key": key, "content_type": content_type})
        return f"https://cdn.example/{key}"

    monkeypatch.setattr(storage, "s3_enabled", lambda: True)
    monkeypatch.setattr(storage, "put_object", fake_put_object)

    ref_audio_url, sample_rate, duration_sec = await storage.save_audio(
        "user-1",
        "vpf_123",
        _source_wav_bytes(),
    )

    assert ref_audio_url == "https://cdn.example/voice-profiles/user-1/vpf_123.wav"
    assert sample_rate == 24000
    assert duration_sec > 0
    assert len(uploaded) == 1
    assert uploaded[0]["key"] == "voice-profiles/user-1/vpf_123.wav"
    assert uploaded[0]["content_type"] == "audio/wav"
    assert bytes(uploaded[0]["data"]).startswith(b"RIFF")


@pytest.mark.asyncio
async def test_save_audio_keeps_local_fallback_when_s3_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(storage, "_USER_VOICES_DIR", tmp_path)
    monkeypatch.setattr(storage, "s3_enabled", lambda: False)

    ref_audio_url, sample_rate, duration_sec = await storage.save_audio(
        "user-2",
        "vpf_456",
        _source_wav_bytes(),
    )

    saved_path = Path(ref_audio_url)
    assert saved_path == tmp_path / "user-2" / "vpf_456.wav"
    assert sample_rate == 24000
    assert duration_sec > 0
    assert storage.load_audio(ref_audio_url).startswith(b"RIFF")

    storage.delete_audio(ref_audio_url)
    assert not saved_path.exists()


def test_load_audio_reads_http_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        content = b"RIFFremoteWAVE"

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, timeout: float) -> FakeResponse:
        assert url == "https://cdn.example/ref.wav"
        assert timeout == storage._REF_DOWNLOAD_TIMEOUT_SEC
        return FakeResponse()

    monkeypatch.setattr(storage.httpx, "get", fake_get)

    assert storage.load_audio("https://cdn.example/ref.wav") == b"RIFFremoteWAVE"


def _source_wav_bytes() -> bytes:
    sample_rate = 16000
    seconds = 0.2
    samples = np.linspace(0.0, seconds, int(sample_rate * seconds), endpoint=False)
    wave = (0.1 * np.sin(2.0 * np.pi * 440.0 * samples)).astype(np.float32)
    return encode_wav_bytes(wave, sample_rate)
