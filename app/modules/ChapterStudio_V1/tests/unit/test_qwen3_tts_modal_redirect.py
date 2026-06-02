"""Qwen3 Modal TTS 커넥터의 네이티브 호출 테스트."""
from __future__ import annotations

import base64
import io
import wave
from unittest.mock import AsyncMock

import numpy as np
import pytest

from ai_connectors.errors import AuthError, InferenceError, ModelNotFoundError
from ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from ai_connectors.tts import qwen3_tts_modal_connector as qwen_module
from ai_connectors.tts_schemas import TTSRequest
from common.audio_io import encode_wav_bytes

_APP_NAME = "qwen3-tts-test"
_SERVER_CLASS = "Qwen3TTSServer"
_REF_AUDIO_BYTES = b"ref-audio-bytes"


class _FakeRemote:
    def __init__(self, aio: AsyncMock) -> None:
        self.aio = aio


class _FakeMethod:
    def __init__(self, aio: AsyncMock) -> None:
        self.remote = _FakeRemote(aio)


class _FakeServer:
    def __init__(self, aio: AsyncMock) -> None:
        self.synthesize_remote = _FakeMethod(aio)


class _FakeFactory:
    def __init__(self, server: _FakeServer) -> None:
        self.server = server

    def __call__(self) -> _FakeServer:
        return self.server


def _install_server(
    monkeypatch: pytest.MonkeyPatch,
    aio: AsyncMock,
) -> list[tuple[str, str]]:
    """Modal class 조회를 가짜 서버로 고정해 실호출을 차단한다."""
    calls: list[tuple[str, str]] = []
    server = _FakeServer(aio)

    def _from_name(app_name: str, class_name: str) -> _FakeFactory:
        calls.append((app_name, class_name))
        return _FakeFactory(server)

    monkeypatch.setattr(qwen_module.modal.Cls, "from_name", _from_name)
    return calls


@pytest.mark.asyncio
async def test_native_call_encodes_reference_and_decodes_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_bytes = _wav(np.full(16, 0.25, dtype=np.float32), sample_rate=1000)
    aio = AsyncMock(return_value=_modal_result(audio_bytes, sample_rate=1000))
    lookup_calls = _install_server(monkeypatch, aio)
    connector = qwen_module.Qwen3TTSModalConnector(app_name=_APP_NAME, timeout_sec=10.0)

    result = await connector.synthesize(_request(text="짧은 합성 문장"))

    payload = aio.await_args.kwargs
    assert result.audio_bytes == audio_bytes
    assert result.sample_rate == 1000
    assert result.content_type == "audio/wav"
    assert result.resolved_ref_text == "참조 대본"
    assert base64.b64decode(payload["ref_audio_b64"]) == _REF_AUDIO_BYTES
    assert payload["text"] == "짧은 합성 문장"
    assert payload["ref_text"] == "참조 대본"
    assert payload["language"] == "korean"
    assert payload["speed"] == 1.25
    assert lookup_calls == [(_APP_NAME, _SERVER_CLASS)]


@pytest.mark.asyncio
async def test_multi_segment_native_calls_are_merged_with_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TTS_SEGMENT_PAUSE_MS", "60")
    first = _wav(np.full(10, 0.25, dtype=np.float32), sample_rate=1000)
    second = _wav(np.full(20, 0.5, dtype=np.float32), sample_rate=1000)
    aio = AsyncMock(
        side_effect=[
            _modal_result(first, sample_rate=1000, char_count=81),
            _modal_result(second, sample_rate=1000, char_count=81),
        ]
    )
    _install_server(monkeypatch, aio)
    connector = qwen_module.Qwen3TTSModalConnector(app_name=_APP_NAME, timeout_sec=10.0)
    text = f"{'가' * 80}. {'나' * 80}."

    result = await connector.synthesize(_request(text=text))
    samples = _decode_samples(result.audio_bytes)

    assert aio.await_count == 2
    assert result.segment_count == 2
    assert result.char_count == 162
    assert len(samples) == 10 + 60 + 20
    assert np.all(samples[10:70] == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("remote_error", "expected_error"),
    [
        (qwen_module.modal.exception.NotFoundError("없음"), ModelNotFoundError),
        (qwen_module.modal.exception.AuthError("인증 실패"), AuthError),
        (qwen_module.modal.exception.TimeoutError("초과"), ConnectorTimeoutError),
        (qwen_module.modal.exception.Error("기타 실패"), InferenceError),
    ],
)
async def test_native_modal_errors_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
    remote_error: Exception,
    expected_error: type[Exception],
) -> None:
    aio = AsyncMock(side_effect=remote_error)
    _install_server(monkeypatch, aio)
    connector = qwen_module.Qwen3TTSModalConnector(app_name=_APP_NAME, timeout_sec=10.0)

    with pytest.raises(expected_error):
        await connector._call_endpoint(_request())


def _request(text: str = "HTTP 우회 없는 네이티브 테스트 문장") -> TTSRequest:
    """Modal 네이티브 호출에 전달할 공통 요청을 만든다."""
    return TTSRequest(
        text=text,
        ref_audio_bytes=_REF_AUDIO_BYTES,
        ref_text="참조 대본",
        language="korean",
        speed=1.25,
    )


def _modal_result(
    audio_bytes: bytes,
    sample_rate: int = 24000,
    char_count: int | None = None,
) -> dict[str, object]:
    """Modal 서버가 반환하는 base64 WAV dict 를 만든다."""
    return {
        "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
        "sample_rate": sample_rate,
        "duration_sec": 0.42,
        "latency_ms": 12.5,
        "char_count": char_count if char_count is not None else len(_request().text),
        "ref_text_used": "참조 대본",
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    }


def _wav(samples: np.ndarray, sample_rate: int) -> bytes:
    """테스트 병합 검증용 WAV bytes 를 만든다."""
    return encode_wav_bytes(samples, sample_rate)


def _decode_samples(audio_bytes: bytes) -> np.ndarray:
    """WAV bytes 를 int16 샘플로 되돌려 무음 구간을 확인한다."""
    with wave.open(io.BytesIO(audio_bytes)) as wav_file:
        raw = wav_file.readframes(wav_file.getnframes())
    return np.frombuffer(raw, dtype=np.int16)
