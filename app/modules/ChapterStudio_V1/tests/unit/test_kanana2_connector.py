from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.ai_connectors import kanana2_connector as kanana_module


class FakeRemote:
    def __init__(self, result: object = None, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.payloads: list[dict[str, object]] = []

    async def aio(self, **payload: object) -> object:
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        return self.result


class FakeFunction:
    def __init__(self, remote: FakeRemote) -> None:
        self.remote = remote


class FakeServer:
    def __init__(self, remote: FakeRemote) -> None:
        self.correct = FakeFunction(remote)


class FakeServerFactory:
    def __init__(self, server: FakeServer) -> None:
        self.server = server

    def __call__(self) -> FakeServer:
        return self.server


def _install_server(monkeypatch: pytest.MonkeyPatch, remote: FakeRemote) -> None:
    server = FakeServer(remote)
    monkeypatch.setattr(
        kanana_module.modal.Cls,
        "from_name",
        lambda app_name, class_name: FakeServerFactory(server),
    )


@pytest.mark.asyncio
async def test_polish_calls_modal_correct_and_cleans_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    remote = FakeRemote("교정 결과: 절댓값을 비교할 수 있을까요?")
    _install_server(monkeypatch, remote)

    connector = kanana_module.Kanana2Connector()
    result = await connector.polish("절대값을 비교할 수 있을까요", tone_hint="존댓말")

    assert result == "절댓값을 비교할 수 있을까요?"
    assert remote.payloads[0]["text"] == "절대값을 비교할 수 있을까요"
    assert "말투는 존댓말 유지" in str(remote.payloads[0]["instruction"])


@pytest.mark.asyncio
async def test_polish_failure_returns_original_text(monkeypatch: pytest.MonkeyPatch) -> None:
    remote = FakeRemote(error=RuntimeError("remote failure"))
    _install_server(monkeypatch, remote)

    connector = kanana_module.Kanana2Connector()
    original = "정수的世界里에서 절대값을 비교합니다."

    assert await connector.polish(original) == original
