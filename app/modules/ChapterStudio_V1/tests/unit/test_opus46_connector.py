from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.ai_connectors import opus46_connector as opus_module
from app.modules.ChapterStudio_V1.ai_connectors.errors import AuthError, ConnectorError, ContextLengthExceeded, RateLimitError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest


class TextBlock:
    type = "text"
    text = "기획 완료"


class Usage:
    input_tokens = 3
    output_tokens = 4


class Message:
    content = [TextBlock()]
    usage = Usage()
    stop_reason = "end_turn"


class FakeMessages:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def create(self, **payload: object) -> Message:
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return Message()


class FakeClient:
    def __init__(self, messages: FakeMessages) -> None:
        self.messages = messages


def _install_client(monkeypatch: pytest.MonkeyPatch, messages: FakeMessages) -> None:
    monkeypatch.setattr(opus_module, "anthropic_api_key", lambda: "key")
    monkeypatch.setattr(opus_module, "AsyncAnthropic", lambda: FakeClient(messages))


def test_model_id_is_locked() -> None:
    assert opus_module._MODEL_ID == "claude-opus-4-6"


@pytest.mark.asyncio
async def test_generate_uses_locked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = FakeMessages()
    _install_client(monkeypatch, messages)
    conn = opus_module.Opus46Connector()
    resp = await conn.generate(ChapterAIRequest(user="기획", max_tokens=32, temperature=0.2))
    assert resp.text == "기획 완료"
    assert messages.calls[0]["model"] == opus_module._MODEL_ID


def test_missing_key_raises_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opus_module, "anthropic_api_key", lambda: None)
    with pytest.raises(AuthError):
        opus_module.Opus46Connector()


@pytest.mark.asyncio
async def test_auth_error_maps_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    class VendorAuthError(Exception):
        pass

    monkeypatch.setattr(opus_module, "_AnthropicAuthError", VendorAuthError)
    _install_client(monkeypatch, FakeMessages(VendorAuthError("bad")))
    with pytest.raises(AuthError):
        await opus_module.Opus46Connector().generate(ChapterAIRequest(user="u", max_tokens=32, temperature=0.2))


@pytest.mark.asyncio
async def test_rate_error_maps_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    class VendorRateError(Exception):
        pass

    monkeypatch.setattr(opus_module, "_AnthropicRateLimitError", VendorRateError)
    _install_client(monkeypatch, FakeMessages(VendorRateError("rate")))
    with pytest.raises(RateLimitError):
        await opus_module.Opus46Connector().generate(ChapterAIRequest(user="u", max_tokens=32, temperature=0.2))


@pytest.mark.asyncio
async def test_context_bad_request_maps_context(monkeypatch: pytest.MonkeyPatch) -> None:
    class VendorBadRequest(Exception):
        pass

    monkeypatch.setattr(opus_module, "_AnthropicBadRequestError", VendorBadRequest)
    _install_client(monkeypatch, FakeMessages(VendorBadRequest("context too long")))
    with pytest.raises(ContextLengthExceeded):
        await opus_module.Opus46Connector().generate(ChapterAIRequest(user="u", max_tokens=32, temperature=0.2))


@pytest.mark.asyncio
async def test_other_bad_request_maps_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    class VendorBadRequest(Exception):
        pass

    monkeypatch.setattr(opus_module, "_AnthropicBadRequestError", VendorBadRequest)
    _install_client(monkeypatch, FakeMessages(VendorBadRequest("bad payload")))
    with pytest.raises(ConnectorError):
        await opus_module.Opus46Connector().generate(ChapterAIRequest(user="u", max_tokens=32, temperature=0.2))
