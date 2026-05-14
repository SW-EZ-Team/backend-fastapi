from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.ai_connectors import registry
from app.modules.ChapterStudio_V1.ai_connectors.errors import ModelNotFoundError
from app.modules.ChapterStudio_V1.tests.mocks.qwen27b_mock_connector import Qwen27BMockConnector
from app.modules.ChapterStudio_V1.tests.mocks.tts_v1_mock_connector import TTSV1MockConnector


class CloseableTTSConnector:
    name = "closeable_tts"

    def __init__(self) -> None:
        self.closed = False

    async def synthesize(self, text: str, voice: str = "f1") -> dict[str, str | float]:
        return {"audio_url": "mock://audio", "duration_sec": 0.1}

    async def aclose(self) -> None:
        self.closed = True

    def supports(self, feature: str) -> bool:
        return feature in {"tts_synthesis"}


def test_unknown_connector_raises_model_not_found() -> None:
    with pytest.raises(ModelNotFoundError):
        registry.get_connector("missing")


def test_same_connector_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry._REGISTRY, "qwen27b_mock", Qwen27BMockConnector)
    registry.clear_cache()
    first = registry.get_connector("qwen27b_mock")
    second = registry.get_connector("qwen27b_mock")
    assert first is second


def test_clear_cache_creates_new_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry._REGISTRY, "qwen27b_mock", Qwen27BMockConnector)
    registry.clear_cache()
    first = registry.get_connector("qwen27b_mock")
    registry.clear_cache()
    second = registry.get_connector("qwen27b_mock")
    assert first is not second


def test_get_text_connector_uses_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry._REGISTRY, "qwen27b_mock", Qwen27BMockConnector)
    monkeypatch.setattr(registry, "active_text_model", lambda: "qwen27b_mock")
    registry.clear_cache()
    assert registry.get_text_connector().name == "qwen27b_mock"


def test_get_tts_connector_requires_tts_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry._REGISTRY, "tts_v1_mock", TTSV1MockConnector)
    monkeypatch.setattr(registry, "active_tts_model", lambda: "tts_v1_mock")
    registry.clear_cache()
    assert registry.get_tts_connector().name == "tts_v1_mock"


@pytest.mark.asyncio
async def test_close_all_closes_cached_async_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry._REGISTRY, "closeable_tts", CloseableTTSConnector)
    registry.clear_cache()
    connector = registry.get_connector("closeable_tts")
    await registry.close_all()
    assert isinstance(connector, CloseableTTSConnector)
    assert connector.closed is True
    assert registry._CACHE == {}
