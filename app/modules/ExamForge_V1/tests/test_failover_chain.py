"""ExamForge 폴백 체인(Gemini → OpenAI → Claude Sonnet) 검증.

- 매 요청 primary 우선(요청 간 sticky 상태 없음)
- OpenAI 실패 → Claude 성공
- AuthError/생성 실패 단계는 영구 제외하고 다음 단계 진행
- 전부 실패 → 마지막 에러 전파
- 키 유무에 따른 체인 구성(_fallback_stage_factories / _build_gemini_genai_connector)
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.ExamForge_V1.common import ai_bridge
from app.modules.ExamForge_V1.common._ai_schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ExamForge_V1.common.errors import AuthError, ConnectorError, RateLimitError


def _req() -> ChapterAIRequest:
    return ChapterAIRequest(system="", user="체인 테스트", max_tokens=128, temperature=0.2)


class _StubConnector:
    """성공/실패를 제어할 수 있는 더미 커넥터(ExamForge generate 시그니처)."""

    def __init__(self, name: str, error: Exception | None = None) -> None:
        self.name = name
        self.error = error
        self.call_count = 0

    async def generate(self, req: ChapterAIRequest, budget=None) -> ChapterAIResponse:
        self.call_count += 1
        if self.error is not None:
            raise self.error
        return ChapterAIResponse(
            text=f"{self.name} 응답", model=self.name, input_tokens=1, output_tokens=1, finish_reason="stop"
        )

    def supports(self, feature: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_openai_failure_falls_through_to_claude() -> None:
    """primary(Gemini) 실패 → OpenAI 실패 → Claude 성공."""
    gemini = _StubConnector("gemini_flash", error=RateLimitError("429"))
    openai = _StubConnector("openai_text", error=ConnectorError("openai down"))
    claude = _StubConnector("claude_sonnet")
    chain = ai_bridge._OpenAIFailoverConnector(
        gemini, fallback_factories=[lambda: openai, lambda: claude]
    )

    response = await chain.generate(_req())

    assert response.text == "claude_sonnet 응답"
    assert openai.call_count == 1
    assert claude.call_count == 1


@pytest.mark.asyncio
async def test_per_request_semantics_primary_retried_next_request() -> None:
    """요청 간 sticky 상태 없음 — 다음 요청은 다시 primary부터 시도한다."""
    gemini = _StubConnector("gemini_flash", error=RateLimitError("429"))
    claude = _StubConnector("claude_sonnet")
    chain = ai_bridge._OpenAIFailoverConnector(gemini, fallback_factories=[lambda: claude])

    await chain.generate(_req())
    gemini.error = None  # primary 회복
    response = await chain.generate(_req())

    assert response.text == "gemini_flash 응답"
    assert gemini.call_count == 2
    assert claude.call_count == 1


@pytest.mark.asyncio
async def test_auth_error_stage_is_skipped_permanently() -> None:
    """AuthError 단계는 영구 제외되고 다음 요청부터 호출되지 않는다."""
    gemini = _StubConnector("gemini_flash", error=RateLimitError("429"))
    openai = _StubConnector("openai_text", error=AuthError("invalid key"))
    claude = _StubConnector("claude_sonnet")
    chain = ai_bridge._OpenAIFailoverConnector(
        gemini, fallback_factories=[lambda: openai, lambda: claude]
    )

    first = await chain.generate(_req())
    second = await chain.generate(_req())

    assert first.text == "claude_sonnet 응답"
    assert second.text == "claude_sonnet 응답"
    assert openai.call_count == 1


@pytest.mark.asyncio
async def test_stage_construction_failure_skips_to_next() -> None:
    """폴백 생성자가 RuntimeError(키 누락)를 올리면 그 단계만 건너뛴다."""
    gemini = _StubConnector("gemini_flash", error=RateLimitError("429"))
    claude = _StubConnector("claude_sonnet")

    def _broken_factory() -> _StubConnector:
        raise RuntimeError("claude_sonnet: ANTHROPIC_API_KEY 필요")

    chain = ai_bridge._OpenAIFailoverConnector(
        gemini, fallback_factories=[_broken_factory, lambda: claude]
    )

    response = await chain.generate(_req())

    assert response.text == "claude_sonnet 응답"


@pytest.mark.asyncio
async def test_all_stages_fail_raises_last_error() -> None:
    """전부 실패하면 마지막 단계의 에러가 그대로 전파된다."""
    gemini = _StubConnector("gemini_flash", error=RateLimitError("429"))
    openai = _StubConnector("openai_text", error=ConnectorError("openai down"))
    claude = _StubConnector("claude_sonnet", error=ConnectorError("claude down"))
    chain = ai_bridge._OpenAIFailoverConnector(
        gemini, fallback_factories=[lambda: openai, lambda: claude]
    )

    with pytest.raises(ConnectorError, match="claude down"):
        await chain.generate(_req())


@pytest.mark.asyncio
async def test_single_factory_signature_still_works() -> None:
    """기존 단일 fallback_factory 시그니처는 길이 1짜리 체인으로 동작한다(하위 호환)."""
    gemini = _StubConnector("gemini_flash", error=RateLimitError("429"))
    openai = _StubConnector("openai_text")
    chain = ai_bridge._OpenAIFailoverConnector(gemini, lambda: openai)

    response = await chain.generate(_req())

    assert response.text == "openai_text 응답"


# ── 키 유무에 따른 체인 구성 ─────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolate_fallback_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """프로바이더 폴백 키를 모두 제거해 테스트별 명시 설정만 유효하게 한다."""
    for key in ("OPENAI_API_KEY", "OPENAI_FALLBACK_ENABLED", "ANTHROPIC_API_KEY", "CLAUDE_SONNET_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_stage_factories_include_openai_then_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    assert len(ai_bridge._fallback_stage_factories()) == 2


def test_stage_factories_claude_only_when_openai_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    factories = ai_bridge._fallback_stage_factories()

    assert len(factories) == 1
    connector = factories[0]()
    assert getattr(connector, "name", "") == "claude_sonnet"


def test_stage_factories_empty_without_any_key() -> None:
    assert ai_bridge._fallback_stage_factories() == []


def test_stage_factories_kill_switch_excludes_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    assert len(ai_bridge._fallback_stage_factories()) == 1


class _FakeGeminiModels:
    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        return SimpleNamespace(text="본문", usage_metadata=None, candidates=[])


class _FakeGeminiClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.models = _FakeGeminiModels()

    def close(self) -> None:
        return None


def test_build_returns_raw_gemini_without_fallback_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """폴백 후보 키가 없으면 raw Gemini 커넥터를 그대로 반환한다(기존 동작 보존)."""
    from app.modules.ExamForge_V1.common import _connector_gemini_genai as gemini_module

    monkeypatch.setattr(gemini_module.genai, "Client", _FakeGeminiClient)
    monkeypatch.setenv("GOOGLE_API_KEY", "gemini-key")

    connector = ai_bridge._build_gemini_genai_connector()

    assert not isinstance(connector, ai_bridge._OpenAIFailoverConnector)


def test_build_wraps_with_chain_when_claude_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude 키만 있어도 폴백 체인 래퍼로 감싼다."""
    from app.modules.ExamForge_V1.common import _connector_gemini_genai as gemini_module

    monkeypatch.setattr(gemini_module.genai, "Client", _FakeGeminiClient)
    monkeypatch.setenv("GOOGLE_API_KEY", "gemini-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    connector = ai_bridge._build_gemini_genai_connector()

    assert isinstance(connector, ai_bridge._OpenAIFailoverConnector)
    assert len(connector._fallback_factories) == 1
