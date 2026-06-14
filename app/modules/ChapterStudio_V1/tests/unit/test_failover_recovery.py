"""FailoverAIConnector 주 커넥터 복귀(recovery) 검증.

폴백 전환이 영구가 아니라 TEXT_FALLBACK_RECOVERY_SEC 간격 후 주 커넥터를
1회 재시도해 회로를 닫는지 확인한다 (tests/test_gemini_stabilization.py 의
공유 _failover_text 복귀 테스트와 동일한 시나리오).
"""
from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.ai_connectors import failover_connector as failover_module
from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError, RateLimitError
from app.modules.ChapterStudio_V1.ai_connectors.failover_connector import FailoverAIConnector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse


def _req() -> ChapterAIRequest:
    return ChapterAIRequest(user="복귀 테스트", max_tokens=128, temperature=0.2)


class _StubConnector:
    """성공/실패를 제어할 수 있는 더미 커넥터."""

    def __init__(self, name: str, error: ConnectorError | None = None) -> None:
        self.name = name
        self.error = error
        self.call_count = 0

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        self.call_count += 1
        if self.error is not None:
            raise self.error
        return ChapterAIResponse(
            text=f"{self.name} 응답",
            model=self.name,
            input_tokens=1,
            output_tokens=1,
            finish_reason="stop",
        )

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return False


def _patch_failover_clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    """failover_connector 모듈의 monotonic을 가짜 시계로 바꾼다."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(failover_module.time, "monotonic", lambda: clock["now"])
    return clock


def _build_chain(
    primary: _StubConnector, fallback: _StubConnector, *, name: str
) -> FailoverAIConnector:
    return FailoverAIConnector(
        primary_factory=lambda: primary,
        fallback_factory=lambda: fallback,
        name=name,
        failure_threshold=1,
    )


async def test_failover_recovers_primary_after_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """폴백 전환 후 복귀 간격이 지나면 주 커넥터를 재시도해 회로를 닫는다."""
    monkeypatch.setenv("TEXT_FALLBACK_RECOVERY_SEC", "60")
    clock = _patch_failover_clock(monkeypatch)

    primary = _StubConnector("qwen", error=RateLimitError("429"))
    fallback = _StubConnector("sonnet", error=None)
    chain = _build_chain(primary, fallback, name="recovery_chain")

    # 1차: 주 실패 → 폴백 전환
    response = await chain.generate(_req())
    assert response.text == "sonnet 응답"
    assert chain.fallback_active is True

    # 간격 도달 전에는 주 커넥터를 다시 호출하지 않는다
    clock["now"] += 30.0
    await chain.generate(_req())
    assert primary.call_count == 1

    # 간격 경과 + 주 커넥터 회복 → 복귀 성공, 회로 닫힘
    primary.error = None
    clock["now"] += 31.0
    response = await chain.generate(_req())
    assert response.text == "qwen 응답"
    assert chain.fallback_active is False
    assert chain.failure_count == 0

    # 복귀 후에는 주 커넥터가 계속 응답한다
    response = await chain.generate(_req())
    assert response.text == "qwen 응답"


async def test_failover_probe_failure_stays_on_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """복귀 시도가 실패하면 폴백을 유지하고 다음 시도를 간격만큼 미룬다."""
    monkeypatch.setenv("TEXT_FALLBACK_RECOVERY_SEC", "60")
    clock = _patch_failover_clock(monkeypatch)

    primary = _StubConnector("qwen", error=RateLimitError("429"))
    fallback = _StubConnector("sonnet", error=None)
    chain = _build_chain(primary, fallback, name="recovery_chain")

    await chain.generate(_req())  # 폴백 전환 (주 1회 호출)
    clock["now"] += 61.0
    response = await chain.generate(_req())  # 복귀 시도 실패 → 폴백 응답
    assert response.text == "sonnet 응답"
    assert chain.fallback_active is True
    assert primary.call_count == 2

    # 새 간격이 지나기 전에는 다시 시도하지 않는다
    clock["now"] += 30.0
    await chain.generate(_req())
    assert primary.call_count == 2


async def test_failover_recovery_disabled_when_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TEXT_FALLBACK_RECOVERY_SEC=0이면 기존 영구 폴백 동작을 유지한다."""
    monkeypatch.setenv("TEXT_FALLBACK_RECOVERY_SEC", "0")
    clock = _patch_failover_clock(monkeypatch)

    primary = _StubConnector("qwen", error=RateLimitError("429"))
    fallback = _StubConnector("sonnet", error=None)
    chain = _build_chain(primary, fallback, name="sticky_chain")

    await chain.generate(_req())
    primary.error = None
    clock["now"] += 100_000.0
    response = await chain.generate(_req())
    assert response.text == "sonnet 응답"
    assert chain.fallback_active is True
    assert primary.call_count == 1


async def test_failover_recovery_applies_to_generate_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """generate_batch 경로도 동일하게 복귀한다."""
    monkeypatch.setenv("TEXT_FALLBACK_RECOVERY_SEC", "60")
    clock = _patch_failover_clock(monkeypatch)

    primary = _StubConnector("qwen", error=RateLimitError("429"))
    fallback = _StubConnector("sonnet", error=None)
    chain = _build_chain(primary, fallback, name="batch_recovery_chain")

    responses = await chain.generate_batch([_req(), _req()])
    assert all(r.text == "sonnet 응답" for r in responses)
    assert chain.fallback_active is True

    primary.error = None
    clock["now"] += 61.0
    responses = await chain.generate_batch([_req(), _req()])
    assert all(r.text == "qwen 응답" for r in responses)
    assert chain.fallback_active is False
