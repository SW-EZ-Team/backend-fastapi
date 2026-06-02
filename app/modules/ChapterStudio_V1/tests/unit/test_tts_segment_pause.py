from __future__ import annotations

import io
import wave

import numpy as np
import pytest

from ai_connectors.tts._text_segmentation import default_segment_pause_ms, merge_segment_responses
from ai_connectors.tts_schemas import TTSResponse
from common.audio_io import encode_wav_bytes


def test_default_segment_pause_ms_defaults_to_sixty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TTS_SEGMENT_PAUSE_MS", raising=False)

    assert default_segment_pause_ms() == 60


def test_default_segment_pause_ms_reads_env_and_clamps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TTS_SEGMENT_PAUSE_MS", "60")
    assert default_segment_pause_ms() == 60

    monkeypatch.setenv("TTS_SEGMENT_PAUSE_MS", "-1")
    assert default_segment_pause_ms() == 0

    monkeypatch.setenv("TTS_SEGMENT_PAUSE_MS", "700")
    assert default_segment_pause_ms() == 500

    monkeypatch.setenv("TTS_SEGMENT_PAUSE_MS", "잘못된값")
    assert default_segment_pause_ms() == 60


def test_merge_segment_responses_inserts_sixty_ms_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample_rate = 1000
    monkeypatch.setenv("TTS_SEGMENT_PAUSE_MS", "60")
    first = _response(np.full(10, 0.25, dtype=np.float32), sample_rate)
    second = _response(np.full(20, 0.5, dtype=np.float32), sample_rate)

    merged = merge_segment_responses([first, second], sample_rate)
    samples = _decode_samples(merged)

    assert len(samples) == 10 + int(sample_rate * 0.06) + 20
    assert np.all(samples[10:70] == 0)


def _response(audio: np.ndarray, sample_rate: int) -> TTSResponse:
    return TTSResponse(
        audio_bytes=encode_wav_bytes(audio, sample_rate),
        sample_rate=sample_rate,
        content_type="audio/wav",
        duration_sec=len(audio) / sample_rate,
        latency_ms=0.0,
        char_count=1,
        model="test",
    )


def _decode_samples(audio_bytes: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(audio_bytes)) as wav_file:
        raw = wav_file.readframes(wav_file.getnframes())
    return np.frombuffer(raw, dtype=np.int16)
