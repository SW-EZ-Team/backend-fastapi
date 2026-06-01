"""Gemini 멀티모달 커넥터 오프라인 단위 테스트."""
from __future__ import annotations

import asyncio
import io
import struct
import wave
from types import SimpleNamespace

import pytest

import ai_connectors._gemini_common as gemini_common
from ai_connectors.asr.gemini_asr_connector import GeminiASRConnector
from ai_connectors.errors import AuthError, InferenceError
from ai_connectors.ocr.gemini_ocr_connector import GeminiOCRConnector
from ai_connectors.registry import get_asr_connector, get_ocr_connector, get_tts_connector
from ai_connectors.schemas import ASRRequest, OCRRequest
from ai_connectors.tts.gemini_tts_connector import GeminiTTSConnector
from ai_connectors.tts_schemas import TTSRequest


class _FakeConfig:
    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakePart:
    def __init__(self, data: bytes, mime_type: str) -> None:
        self.data = data
        self.mime_type = mime_type

    @classmethod
    def from_bytes(cls, data: bytes, mime_type: str) -> "_FakePart":
        return cls(data=data, mime_type=mime_type)


class _FakeTypes:
    GenerateContentConfig = _FakeConfig
    SpeechConfig = _FakeConfig
    VoiceConfig = _FakeConfig
    PrebuiltVoiceConfig = _FakeConfig
    Part = _FakePart


class _FakeModels:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class _FakeClient:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


class _FakeGenai:
    types = _FakeTypes

    def __init__(self, models: _FakeModels) -> None:
        self.models = models
        self.api_keys: list[str] = []

    def Client(self, api_key: str) -> _FakeClient:
        self.api_keys.append(api_key)
        return _FakeClient(self.models)


def _patch_genai(monkeypatch: pytest.MonkeyPatch, response: object) -> tuple[_FakeModels, _FakeGenai]:
    """google-genai import 경로를 가짜 모듈로 교체한다."""
    models = _FakeModels(response)
    fake_genai = _FakeGenai(models)
    monkeypatch.setattr(gemini_common, "load_genai_module", lambda: fake_genai)
    return models, fake_genai


def _tts_response(pcm_data: bytes) -> object:
    """Gemini TTS 응답 구조를 최소 형태로 만든다."""
    inline = SimpleNamespace(data=pcm_data)
    part = SimpleNamespace(inline_data=inline)
    content = SimpleNamespace(parts=[part])
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


def _wav_bytes(sample_rate: int = 16000) -> bytes:
    """ASR 테스트용 짧은 WAV 바이트를 만든다."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack("<hhhh", 0, 1000, -1000, 0))
    return buf.getvalue()


def test_tts_passes_config_and_wraps_pcm_as_wav(monkeypatch: pytest.MonkeyPatch) -> None:
    pcm = struct.pack("<hhh", 0, 1000, -1000)
    models, fake_genai = _patch_genai(monkeypatch, _tts_response(pcm))
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_TTS_MODEL", "gemini-tts-test")
    monkeypatch.setenv("GEMINI_TTS_VOICE", "Kore")

    req = TTSRequest(text="안녕하세요 [whispers]", ref_audio_bytes=b"unused")
    result = asyncio.run(GeminiTTSConnector().synthesize(req))

    call = models.calls[0]
    config = call["config"]
    speech_config = config.speech_config
    voice_config = speech_config.voice_config.prebuilt_voice_config
    assert fake_genai.api_keys == ["test-key"]
    assert call["model"] == "gemini-tts-test"
    assert call["contents"] == "안녕하세요 [whispers]"
    assert config.response_modalities == ["AUDIO"]
    assert voice_config.voice_name == "Kore"
    assert result.audio_bytes[:4] == b"RIFF"
    with wave.open(io.BytesIO(result.audio_bytes), "rb") as wf:
        assert wf.getframerate() == 24000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getnframes() == 3


def test_asr_passes_audio_part_and_parses_text(monkeypatch: pytest.MonkeyPatch) -> None:
    models, _fake_genai = _patch_genai(monkeypatch, SimpleNamespace(text=" 전사 결과 \n"))
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_ASR_MODEL", "gemini-asr-test")
    audio_bytes = _wav_bytes()

    req = ASRRequest(audio_bytes=audio_bytes, language="ko")
    result = asyncio.run(GeminiASRConnector().generate(req))

    call = models.calls[0]
    contents = call["contents"]
    assert call["model"] == "gemini-asr-test"
    assert contents[0].data == audio_bytes
    assert contents[0].mime_type == "audio/wav"
    assert "전사" in contents[1]
    assert result.text == "전사 결과"
    assert result.model == "gemini-asr"


def test_ocr_passes_image_config_and_parses_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    models, _fake_genai = _patch_genai(monkeypatch, SimpleNamespace(text="| A | B |"))
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_OCR_MODEL", "gemini-ocr-test")
    image_bytes = b"\x89PNG\r\n"

    result = asyncio.run(GeminiOCRConnector().recognize(OCRRequest(image_bytes=image_bytes)))

    call = models.calls[0]
    contents = call["contents"]
    config = call["config"]
    assert call["model"] == "gemini-ocr-test"
    assert contents[0].data == image_bytes
    assert contents[0].mime_type == "image/png"
    assert config.temperature == 0.0
    assert "정밀 OCR 엔진" in config.system_instruction
    assert result.text == "| A | B |"
    assert result.model_version == "gemini-ocr"


def test_missing_google_api_key_is_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_genai(monkeypatch, SimpleNamespace(text="unused"))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(AuthError):
        asyncio.run(GeminiTTSConnector().synthesize(TTSRequest(text="안녕", ref_audio_bytes=b"x")))
    with pytest.raises(AuthError):
        asyncio.run(GeminiASRConnector().generate(ASRRequest(audio_bytes=_wav_bytes())))
    with pytest.raises(AuthError):
        asyncio.run(GeminiOCRConnector().recognize(OCRRequest(image_bytes=b"png")))


def test_gemini_api_key_alias_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    models, fake_genai = _patch_genai(monkeypatch, _tts_response(struct.pack("<h", 0)))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    asyncio.run(GeminiTTSConnector().synthesize(TTSRequest(text="안녕", ref_audio_bytes=b"x")))

    assert fake_genai.api_keys == ["gemini-key"]
    assert models.calls[0]["model"] == "gemini-3.1-flash-tts-preview"


def test_vendor_errors_are_inference_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_genai(monkeypatch, RuntimeError("vendor failed"))
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    with pytest.raises(InferenceError):
        asyncio.run(GeminiTTSConnector().synthesize(TTSRequest(text="안녕", ref_audio_bytes=b"x")))
    with pytest.raises(InferenceError):
        asyncio.run(GeminiASRConnector().generate(ASRRequest(audio_bytes=_wav_bytes())))
    with pytest.raises(InferenceError):
        asyncio.run(GeminiOCRConnector().recognize(OCRRequest(image_bytes=b"png")))


def test_registry_returns_gemini_connectors_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert get_tts_connector("gemini-tts").name == "gemini-tts"
    assert get_asr_connector("gemini-asr").name == "gemini-asr"
    assert get_ocr_connector("gemini-ocr").name == "gemini-ocr"
