"""셧다운 설계 검증 — scaledown=비용통제 / un-deploy=명시적 decommission.

[핵심 설계 계약]
- 기본(CHAPTERSTUDIO_MODAL_TEARDOWN=false): connector.shutdown() → no-op, False 반환.
  비용 통제는 scaledown_window=30s가 담당하므로 코드에서 un-deploy를 호출하지 않는다.
- teardown=true: `modal app stop`(un-deploy) 실행 → True/False 반환.
  라이브 서비스에서 이 경로를 타면 다음 요청이 깨지므로 decommission 전용.

검증 항목:
    - teardown=false(기본): 서브프로세스를 호출하지 않고 False 반환(no-op).
    - teardown=true: 서브프로세스를 argv 배열로 호출하고 returncode 0이면 True.
    - teardown=true + returncode != 0: graceful False(예외 없음).
    - shutdown_text_connector: shutdown 지원 커넥터 호출, 미지원은 no-op(False).
    - 셧다운 훅 예외는 graceful False로 흡수.
"""
from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.ai_connectors import qwen27b_modal_connector as qwen_module
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.pipeline import shutdown as shutdown_util

_SUBPROCESS_ATTR = "create_subprocess_" + "exec"


class _FakeProc:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", (b"" if self.returncode == 0 else b"stop failed")


# ── 커넥터 shutdown() 테스트 ──────────────────────────────────────────


@pytest.mark.anyio
async def test_connector_shutdown_is_noop_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """teardown 스위치 OFF(기본) → 서브프로세스 미호출, False 반환(no-op)."""
    monkeypatch.setenv("CHAPTERSTUDIO_MODAL_TEARDOWN", "false")
    subprocess_called = {"called": False}

    async def fake_spawn(*argv: str, **kwargs: object) -> _FakeProc:
        subprocess_called["called"] = True
        return _FakeProc(returncode=0)

    monkeypatch.setattr(qwen_module.asyncio, _SUBPROCESS_ATTR, fake_spawn)
    monkeypatch.setattr(qwen_module.modal.Cls, "from_name", lambda app, cls: _FakeFactory())
    conn = qwen_module.Qwen27BModalConnector()

    result = await conn.shutdown()

    # 기본 경로는 no-op — un-deploy를 호출하지 않는다.
    assert result is False
    assert subprocess_called["called"] is False


@pytest.mark.anyio
async def test_connector_teardown_invokes_modal_app_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """teardown=true → `modal app stop`을 인자 배열로 호출하고 returncode 0이면 True."""
    monkeypatch.setenv("CHAPTERSTUDIO_MODAL_TEARDOWN", "true")
    captured: dict[str, object] = {}

    async def fake_spawn(*argv: str, **kwargs: object) -> _FakeProc:
        captured["argv"] = argv
        return _FakeProc(returncode=0)

    monkeypatch.setattr(qwen_module.asyncio, _SUBPROCESS_ATTR, fake_spawn)
    monkeypatch.setattr(qwen_module.modal.Cls, "from_name", lambda app, cls: _FakeFactory())
    conn = qwen_module.Qwen27BModalConnector()

    result = await conn.shutdown()

    assert result is True
    argv = captured["argv"]
    assert isinstance(argv, tuple)
    assert argv[0] == "modal"
    assert argv[1:3] == ("app", "stop")


@pytest.mark.anyio
async def test_connector_teardown_returns_false_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """teardown=true + returncode != 0 → graceful False(예외 없음)."""
    monkeypatch.setenv("CHAPTERSTUDIO_MODAL_TEARDOWN", "true")

    async def fake_spawn(*argv: str, **kwargs: object) -> _FakeProc:
        return _FakeProc(returncode=1)

    monkeypatch.setattr(qwen_module.asyncio, _SUBPROCESS_ATTR, fake_spawn)
    monkeypatch.setattr(qwen_module.modal.Cls, "from_name", lambda app, cls: _FakeFactory())
    conn = qwen_module.Qwen27BModalConnector()

    assert await conn.shutdown() is False


# ── shutdown_text_connector 유틸 테스트 ──────────────────────────────


@pytest.mark.anyio
async def test_util_calls_shutdown_hook_on_supporting_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    """shutdown 지원 커넥터 → 훅 호출(기본 no-op이지만 호출 자체는 일어난다)."""
    connector = _ShutdownConnector(result=False)  # 기본 no-op → False
    monkeypatch.setattr(shutdown_util, "get_text_connector", lambda: connector)

    ok = await shutdown_util.shutdown_text_connector()

    # 커넥터가 no-op(False)를 반환해도 훅 자체는 1회 호출됐다.
    assert ok is False
    assert connector.shutdown_calls == 1


@pytest.mark.anyio
async def test_util_noop_on_connector_without_shutdown_support(monkeypatch: pytest.MonkeyPatch) -> None:
    """shutdown 미지원 커넥터(codex/claude) → 유틸 자체가 no-op(False)."""
    connector = _NoShutdownConnector()
    monkeypatch.setattr(shutdown_util, "get_text_connector", lambda: connector)

    assert await shutdown_util.shutdown_text_connector() is False


@pytest.mark.anyio
async def test_util_graceful_when_shutdown_hook_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """shutdown 훅이 예외를 던져도 graceful False — 본 작업 성공 불변."""
    connector = _ShutdownConnector(result=True, raise_exc=True)
    monkeypatch.setattr(shutdown_util, "get_text_connector", lambda: connector)

    assert await shutdown_util.shutdown_text_connector() is False


# ── fake 보조 ────────────────────────────────────────────────────────


class _FakeFactory:
    def __call__(self) -> object:
        return object()


class _ShutdownConnector:
    name = "shutdown_fake"

    def __init__(self, result: bool, raise_exc: bool = False) -> None:
        self._result = result
        self._raise = raise_exc
        self.shutdown_calls = 0

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        raise AssertionError("generate는 호출되면 안 된다.")

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        raise AssertionError("generate_batch는 호출되면 안 된다.")

    def supports(self, feature: str) -> bool:
        return feature in {"batch", "shutdown"}

    async def shutdown(self) -> bool:
        self.shutdown_calls += 1
        if self._raise:
            raise RuntimeError("셧다운 훅 실패")
        return self._result


class _NoShutdownConnector:
    name = "no_shutdown_fake"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        raise AssertionError("generate는 호출되면 안 된다.")

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        raise AssertionError("generate_batch는 호출되면 안 된다.")

    def supports(self, feature: str) -> bool:
        return feature == "batch"
