from __future__ import annotations

import asyncio

import pytest

from app.modules.ChapterStudio_V1.ai_connectors import qwen27b_modal_connector as qwen_module
from app.modules.ChapterStudio_V1.ai_connectors.errors import AuthError, ConnectorError, TimeoutError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest


class FakeRemote:
    def __init__(
        self, result: object = None, error: BaseException | None = None, delay_sec: float = 0.0
    ) -> None:
        self.result = result
        self.error = error
        self.delay_sec = delay_sec
        self.payloads: list[dict[str, object]] = []
        self.active = 0
        self.max_active = 0

    async def aio(self, **payload: object) -> object:
        result_index = len(self.payloads)
        self.payloads.append(payload)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay_sec:
                await asyncio.sleep(self.delay_sec)
            if self.error is not None:
                raise self.error
            if isinstance(self.result, list):
                return self.result[result_index]
            return self.result
        finally:
            self.active -= 1


class FakeFunction:
    def __init__(self, remote: FakeRemote) -> None:
        self.remote = remote


class FakeServer:
    def __init__(self, generate_remote: FakeRemote, batch_remote: FakeRemote | None = None) -> None:
        self.generate = FakeFunction(generate_remote)
        self.generate_batch = FakeFunction(batch_remote or generate_remote)


class FakeServerFactory:
    def __init__(self, server: FakeServer) -> None:
        self.server = server

    def __call__(self) -> FakeServer:
        return self.server


def _install_server(
    monkeypatch: pytest.MonkeyPatch,
    remote: FakeRemote,
    batch_remote: FakeRemote | None = None,
) -> None:
    server = FakeServer(remote, batch_remote)
    monkeypatch.setattr(
        qwen_module.modal.Cls,
        "from_name",
        lambda app_name, class_name: FakeServerFactory(server),
    )


@pytest.mark.asyncio
async def test_generate_returns_response(monkeypatch: pytest.MonkeyPatch) -> None:
    remote = FakeRemote({"text": "ok", "input_tokens": 1, "output_tokens": 2, "finish_reason": "stop"})
    _install_server(monkeypatch, remote)
    conn = qwen_module.Qwen27BModalConnector()
    resp = await conn.generate(ChapterAIRequest(user="u", max_tokens=32, temperature=0.2))
    assert resp.text == "ok"
    assert remote.payloads[0]["user"] == "u"


@pytest.mark.asyncio
async def test_generate_batch_uses_concurrent_generate_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    result = [
        {"text": "a", "input_tokens": 1, "output_tokens": 2, "finish_reason": "stop"},
        {"text": "b", "input_tokens": 1, "output_tokens": 2, "finish_reason": "stop"},
    ]
    remote = FakeRemote(result)
    batch_remote = FakeRemote([])
    _install_server(monkeypatch, remote, batch_remote)
    conn = qwen_module.Qwen27BModalConnector()
    req = ChapterAIRequest(system="s", user="u", max_tokens=32, temperature=0.2)
    responses = await conn.generate_batch([req, req])
    assert [item.text for item in responses] == ["a", "b"]
    assert len(remote.payloads) == 2
    assert batch_remote.payloads == []


@pytest.mark.asyncio
async def test_generate_batch_caps_remote_parallelism(monkeypatch: pytest.MonkeyPatch) -> None:
    result = [
        {"text": str(index), "input_tokens": 1, "output_tokens": 2, "finish_reason": "stop"}
        for index in range(5)
    ]
    remote = FakeRemote(result, delay_sec=0.01)
    _install_server(monkeypatch, remote)
    monkeypatch.setattr(qwen_module, "_MAX_REMOTE_INPUTS", 2)
    conn = qwen_module.Qwen27BModalConnector()
    req = ChapterAIRequest(system="s", user="u", max_tokens=32, temperature=0.2)

    responses = await conn.generate_batch([req, req, req, req, req])

    assert [item.text for item in responses] == ["0", "1", "2", "3", "4"]
    assert len(remote.payloads) == 5
    assert remote.max_active == 2


@pytest.mark.asyncio
async def test_connection_error_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    remote = FakeRemote(error=qwen_module.modal.exception.ConnectionError("끊김"))
    _install_server(monkeypatch, remote)
    conn = qwen_module.Qwen27BModalConnector()
    with pytest.raises(TimeoutError):
        await conn.generate(ChapterAIRequest(user="u", max_tokens=32, temperature=0.2))


@pytest.mark.asyncio
async def test_wait_for_timeout_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qwen_module, "_TIMEOUT_SEC", 0.001)
    remote = FakeRemote(
        {"text": "ok", "input_tokens": 1, "output_tokens": 2, "finish_reason": "stop"},
        delay_sec=0.01,
    )
    _install_server(monkeypatch, remote)
    conn = qwen_module.Qwen27BModalConnector()
    with pytest.raises(TimeoutError):
        await conn.generate(ChapterAIRequest(user="u", max_tokens=32, temperature=0.2))


@pytest.mark.asyncio
async def test_auth_error_maps_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    remote = FakeRemote(error=qwen_module.modal.exception.AuthError("인증"))
    _install_server(monkeypatch, remote)
    conn = qwen_module.Qwen27BModalConnector()
    with pytest.raises(AuthError):
        await conn.generate(ChapterAIRequest(user="u", max_tokens=32, temperature=0.2))


@pytest.mark.asyncio
async def test_bad_response_maps_connector_error(monkeypatch: pytest.MonkeyPatch) -> None:
    remote = FakeRemote({"text": "ok"})
    _install_server(monkeypatch, remote)
    conn = qwen_module.Qwen27BModalConnector()
    with pytest.raises(ConnectorError):
        await conn.generate(ChapterAIRequest(user="u", max_tokens=32, temperature=0.2))


def test_supports_batch_and_long_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_server(monkeypatch, FakeRemote({}))
    conn = qwen_module.Qwen27BModalConnector()
    assert conn.supports("batch")
    assert conn.supports("long_context")
