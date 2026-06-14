"""프로바이더 헬스 사전점검 회귀 테스트.

전 프로바이더 쿼터/사용한도 소진 시 비싼 모의고사 생성을 사전 차단하되,
하나라도 살아있으면 절대 막지 않음(거짓 차단 금지)을 검증한다.

라이브 AI 호출 0 — 전부 헬스 캐시 조작 + 가짜 예외 객체로만 검증한다.
"""
from __future__ import annotations

import time

import pytest

from app.modules.ExamForge_V1.common import _provider_health as health


@pytest.fixture(autouse=True)
def _clean_health():
    """각 테스트는 빈 헬스 캐시에서 시작하고 끝나서 서로 격리된다."""
    health.reset()
    yield
    health.reset()


# ── (a) 전 프로바이더 소진 → 사전점검 차단 ────────────────────────────────
def test_all_exhausted_blocks() -> None:
    """체인의 모든 프로바이더가 소진 기록되면 all_exhausted 가 True(차단)."""
    chain = ["gemini_flash", "openai_text", "claude_sonnet"]
    for name in chain:
        health.mark_exhausted(name, reason="quota", ttl_sec=600)
    assert health.all_exhausted(chain) is True


# ── (b) 하나라도 살아있으면 통과(거짓 차단 금지) ──────────────────────────
def test_one_alive_passes() -> None:
    """체인 중 하나라도 미기록(살아있음)이면 all_exhausted 는 False(정상 진행)."""
    chain = ["gemini_flash", "openai_text", "claude_sonnet"]
    health.mark_exhausted("gemini_flash", reason="quota", ttl_sec=600)
    health.mark_exhausted("openai_text", reason="quota", ttl_sec=600)
    # claude_sonnet 은 기록 안 함 → 살아있음
    assert health.all_exhausted(chain) is False


def test_empty_chain_never_blocks() -> None:
    """체인이 비어있으면(활성 체인 미상) 절대 막지 않는다 → False."""
    assert health.all_exhausted([]) is False


# ── (c) until 경과 시 자동 해제 ────────────────────────────────────────────
def test_until_expiry_releases() -> None:
    """until(만료) 시각이 지나면 소진이 자동 해제되어 다시 시도가 허용된다."""
    # 이미 지난 단조시계 시각으로 만료를 설정한다(라이브 대기 없이 검증).
    past = time.monotonic() - 1.0
    health.mark_exhausted("gemini_flash", reason="quota", until_monotonic=past)
    # 만료됐으므로 살아있는 것으로 본다.
    assert health.is_exhausted("gemini_flash") is False
    assert health.all_exhausted(["gemini_flash"]) is False


def test_future_until_still_blocks() -> None:
    """until 이 미래면 여전히 소진 상태로 본다."""
    future = time.monotonic() + 600.0
    health.mark_exhausted("opus46", reason="usage limit", until_monotonic=future)
    assert health.is_exhausted("opus46") is True


def test_mark_keeps_later_expiry() -> None:
    """이미 더 늦은 만료가 있으면 더 짧은 재기록으로 축소되지 않는다(보수적 유지)."""
    far = time.monotonic() + 10_000.0
    health.mark_exhausted("opus46", reason="long", until_monotonic=far)
    health.mark_exhausted("opus46", reason="short", ttl_sec=1)
    assert health.is_exhausted("opus46") is True


# ── regain-access 날짜 파싱 ────────────────────────────────────────────────
def test_parse_regain_until_future_date() -> None:
    """미래 복구일을 파싱하면 양의 만료(현재 단조시계보다 미래)를 돌려준다."""
    msg = (
        "You have reached your specified API usage limits. "
        "You will regain access on 2999-01-01."
    )
    until = health.parse_regain_until(msg)
    assert until is not None
    assert until > time.monotonic()


def test_parse_regain_until_past_date_returns_none() -> None:
    """이미 지난 복구일은 None(차단 안 함 → 기본 TTL 폴백 유도)."""
    msg = "regain access on 2000-01-01"
    assert health.parse_regain_until("정상 메시지") is None
    assert health.parse_regain_until(msg) is None


def test_parse_regain_until_no_marker() -> None:
    """복구일 패턴이 없으면 None."""
    assert health.parse_regain_until("그냥 400 잘못된 요청") is None


# ── (d) passive 기록: 생성 중 만난 영구성 오류를 기록 ─────────────────────
def test_passive_record_anthropic_usage_limit_400() -> None:
    """Anthropic 400 사용한도 오류를 만나면 해당 프로바이더가 소진 기록된다.

    실제 API 호출 없이 가짜 APIStatusError 를 던지는 client 더블로 검증한다.
    """
    import asyncio

    from app.modules.ExamForge_V1.common import _connector_anthropic as ac
    from app.modules.ExamForge_V1.common._ai_schemas import ChapterAIRequest
    from app.modules.ExamForge_V1.common.errors import ConnectorError

    class _FakeStatusError(Exception):
        # anthropic.APIStatusError 의 status_code 속성만 흉내낸다(isinstance 우회용으로
        # 실제 클래스를 패치한다 — 아래 monkeypatch 참조).
        def __init__(self, status_code: int, message: str) -> None:
            self.status_code = status_code
            super().__init__(message)

    class _FakeMessages:
        async def create(self, **_kwargs):  # noqa: ANN003
            raise _FakeStatusError(
                400,
                "You have reached your specified API usage limits. "
                "regain access on 2999-07-01.",
            )

    class _FakeClient:
        def __init__(self) -> None:
            self.messages = _FakeMessages()

    # 커넥터를 생성자 없이 만들어 가짜 client/모델을 직접 주입한다(키 요구 우회).
    conn = ac.AnthropicConnector.__new__(ac.AnthropicConnector)
    conn._client = _FakeClient()  # type: ignore[attr-defined]
    conn._model = "claude-opus-4-6"  # type: ignore[attr-defined]
    conn.name = "opus46"

    # except 절이 잡는 타입을 가짜 예외 클래스로 교체한다(라이브 SDK 호출 없음).
    original = ac.APIStatusError
    ac.APIStatusError = _FakeStatusError  # type: ignore[assignment, misc]
    try:
        with pytest.raises(ConnectorError):
            asyncio.run(
                conn.generate(
                    ChapterAIRequest(
                        system="s", user="u", max_tokens=256, temperature=0.7
                    )
                )
            )
    finally:
        ac.APIStatusError = original  # type: ignore[assignment, misc]

    # passive 기록 확인 — opus46 이 소진으로 표시되어야 한다.
    assert health.is_exhausted("opus46") is True


def test_passive_record_gemini_billing_429() -> None:
    """Gemini 결제성 429 분류 시 gemini_flash 가 소진 기록된다(라이브 호출 없음)."""
    from app.modules.ExamForge_V1.common import _connector_gemini_genai as efg

    class _FakeErr(Exception):
        def __init__(self, code: int, msg: str) -> None:
            self.code = code
            super().__init__(msg)

    billing_msg = (
        "429 RESOURCE_EXHAUSTED. Your prepayment credits are depleted. "
        "Please go to AI Studio to manage your project and billing."
    )
    efg._map_api_error(_FakeErr(429, billing_msg))
    assert health.is_exhausted("gemini_flash") is True


def test_passive_record_openai_insufficient_quota() -> None:
    """OpenAI insufficient_quota 메시지를 헬스가 소진으로 기록한다(헬퍼 직접 검증)."""
    from app.modules.ExamForge_V1.common import _connector_openai as oc

    assert oc._is_billing_exhausted("You exceeded your current quota, insufficient_quota")
    assert not oc._is_billing_exhausted("Rate limit reached for requests per min")
    oc._record_provider_exhausted("openai_text", "insufficient_quota: billing")
    assert health.is_exhausted("openai_text") is True


# ── 사전점검 통합: text_providers_all_exhausted ────────────────────────────
def test_text_providers_precheck_blocks_when_all_down(monkeypatch) -> None:
    """활성 체인 전부 소진이면 text_providers_all_exhausted 가 True."""
    from app.modules.ExamForge_V1.common import ai_bridge

    monkeypatch.setattr(
        ai_bridge, "active_text_provider_chain", lambda: ["opus46"]
    )
    health.mark_exhausted("opus46", reason="usage limit", ttl_sec=600)
    assert ai_bridge.text_providers_all_exhausted() is True


def test_text_providers_precheck_passes_when_one_alive(monkeypatch) -> None:
    """활성 체인 중 하나라도 살아있으면 False(정상 생성 진행)."""
    from app.modules.ExamForge_V1.common import ai_bridge

    monkeypatch.setattr(
        ai_bridge,
        "active_text_provider_chain",
        lambda: ["gemini_flash", "openai_text", "claude_sonnet"],
    )
    health.mark_exhausted("gemini_flash", reason="quota", ttl_sec=600)
    health.mark_exhausted("openai_text", reason="quota", ttl_sec=600)
    # claude_sonnet 미기록 → 살아있음
    assert ai_bridge.text_providers_all_exhausted() is False
