from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.modules.ChapterStudio_V1.ai_connectors import tts_v1_connector as tts_module
from app.modules.ChapterStudio_V1.ai_connectors import tts_audio_storage as storage_module
from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError, TimeoutError


def _install_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_module, "tts_endpoint", lambda: "https://tts.local/synthesize")
    monkeypatch.setattr(tts_module, "tts_ref_audio_path", lambda: None)
    monkeypatch.setattr(tts_module, "tts_ref_text", lambda: None)
    monkeypatch.setattr(tts_module, "tts_timeout_sec", lambda: 60.0)


@pytest.mark.asyncio
async def test_synthesize_returns_valid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_endpoint(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"audio_url": "mock://a", "duration_sec": 1.5})

    conn = tts_module.TTSV1Connector()
    conn._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=60.0)
    result = await conn.synthesize("안녕")
    await conn.aclose()
    assert result == {"audio_url": "mock://a", "duration_sec": 1.5}


@pytest.mark.asyncio
async def test_timeout_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_endpoint(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("느림")

    conn = tts_module.TTSV1Connector()
    conn._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=60.0)
    with pytest.raises(TimeoutError):
        await conn.synthesize("안녕")
    await conn.aclose()


@pytest.mark.asyncio
async def test_http_error_maps_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_endpoint(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    conn = tts_module.TTSV1Connector()
    conn._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=60.0)
    with pytest.raises(ConnectorError):
        await conn.synthesize("안녕")
    await conn.aclose()


@pytest.mark.asyncio
async def test_missing_key_maps_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_endpoint(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"audio_url": "mock://a"})

    conn = tts_module.TTSV1Connector()
    conn._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=60.0)
    with pytest.raises(ConnectorError):
        await conn.synthesize("안녕")
    await conn.aclose()


@pytest.mark.asyncio
async def test_json_endpoint_rejects_file_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_endpoint(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"audio_url": "file:///tmp/a.wav", "duration_sec": 1.5})

    conn = tts_module.TTSV1Connector()
    conn._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=60.0)
    with pytest.raises(ConnectorError):
        await conn.synthesize("안녕")
    await conn.aclose()


@pytest.mark.asyncio
async def test_audio_endpoint_saves_wav_and_returns_media_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ref_audio = tmp_path / "ref.wav"
    out_dir = tmp_path / "out"
    ref_audio.write_bytes(b"RIFF....WAVE")
    _install_endpoint(monkeypatch)
    monkeypatch.setattr(tts_module, "tts_ref_audio_path", lambda: ref_audio)
    monkeypatch.setattr(tts_module, "tts_ref_text", lambda: "기준 음성 문장입니다.")
    monkeypatch.setattr(storage_module, "s3_enabled", lambda: False)
    monkeypatch.setattr(storage_module, "tts_output_dir", lambda: out_dir)
    monkeypatch.setattr(storage_module, "tts_media_url", lambda filename: f"/media/tts/{filename}")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.content
        return httpx.Response(
            200,
            content=b"RIFFaudio",
            headers={"content-type": "audio/wav", "x-duration-sec": "2.5"},
        )

    conn = tts_module.TTSV1Connector()
    conn._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=60.0)
    result = await conn.synthesize("합성할 대본입니다.", voice="teacher-a")
    await conn.aclose()

    assert str(result["audio_url"]).startswith("/media/tts/")
    assert not str(result["audio_url"]).startswith("file://")
    assert result["duration_sec"] == 2.5
    assert len(list(out_dir.glob("*.wav"))) == 1


@pytest.mark.asyncio
async def test_audio_endpoint_uploads_to_s3_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"RIFF....WAVE")
    uploaded: list[dict[str, object]] = []
    _install_endpoint(monkeypatch)
    monkeypatch.setattr(tts_module, "tts_ref_audio_path", lambda: ref_audio)
    monkeypatch.setattr(tts_module, "tts_ref_text", lambda: "기준 음성 문장입니다.")
    monkeypatch.setattr(storage_module, "s3_enabled", lambda: True)

    async def fake_put_object(data: bytes, key: str, content_type: str) -> str:
        uploaded.append({"data": data, "key": key, "content_type": content_type})
        return f"https://cdn.example/{key}"

    monkeypatch.setattr(storage_module, "put_object", fake_put_object)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"RIFFaudio",
            headers={"content-type": "audio/wav", "x-duration-sec": "2.5"},
        )

    conn = tts_module.TTSV1Connector()
    conn._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=60.0)
    result = await conn.synthesize("합성할 대본입니다.", voice="teacher-a")
    await conn.aclose()

    assert str(uploaded[0]["key"]).startswith("tts/")
    assert str(uploaded[0]["key"]).endswith(".wav")
    assert uploaded[0]["content_type"] == "audio/wav"
    assert result["audio_url"] == f"https://cdn.example/{uploaded[0]['key']}"
    assert not str(result["audio_url"]).startswith("file://")


def test_missing_endpoint_raises_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_module, "tts_endpoint", lambda: None)
    with pytest.raises(ConnectorError):
        tts_module.TTSV1Connector()
