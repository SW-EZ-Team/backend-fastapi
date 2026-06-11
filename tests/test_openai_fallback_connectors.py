"""OpenAI 폴백 커넥터·레지스트리 자동 래핑 오프라인 단위 테스트.

(a) get_text_connector 가 OPENAI_API_KEY 유무/킬스위치에 따라 FailoverAIConnector 또는
    raw Gemini 커넥터를 반환하는지 검증한다.
(b) OpenAIConnector.generate 가 ChapterAIRequest 를 chat.completions 인자로 정확히
    매핑하는지 가짜 클라이언트로 검증한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from ai_connectors import _registry_text as root_registry
from ai_connectors._failover_text import FailoverAIConnector
from ai_connectors._openai_common import clamp_openai_max_tokens
from ai_connectors.text import gemini_connector as root_gemini
from ai_connectors.text import openai_connector as root_openai
from ai_connectors.text.openai_connector import OpenAIConnector
from ai_connectors.text_schemas import ChapterAIRequest


# --- 텍스트 커넥터 가짜 google-genai 클라이언트 (Gemini 생성 단계만 통과시키면 충분) ---


class _FakeGeminiModels:
    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        return SimpleNamespace(text="본문", usage_metadata=None, candidates=[])


class _FakeGeminiClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.models = _FakeGeminiModels()

    def close(self) -> None:
        return None


@pytest.fixture()
def patch_gemini_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini 커넥터 생성이 실제 키 없이도 통과하도록 클라이언트를 교체한다."""
    monkeypatch.setattr(root_gemini.genai, "Client", _FakeGeminiClient)
    monkeypatch.setenv("GOOGLE_API_KEY", "gemini-key")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")


def test_registry_wraps_gemini_with_failover_when_openai_key_set(
    monkeypatch: pytest.MonkeyPatch, patch_gemini_client: None
) -> None:
    """OPENAI_API_KEY 가 있으면 get_text_connector 가 FailoverAIConnector 를 반환한다."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("OPENAI_FALLBACK_ENABLED", raising=False)

    connector = root_registry.get_text_connector("gemini_flash")

    assert isinstance(connector, FailoverAIConnector)
    assert connector.primary_name == "gemini_flash"
    assert connector.supports("fallback") is True


def test_registry_returns_raw_gemini_when_openai_key_unset(
    monkeypatch: pytest.MonkeyPatch, patch_gemini_client: None
) -> None:
    """OPENAI_API_KEY 가 없으면 raw Gemini 커넥터를 그대로 반환한다(기존 동작)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    connector = root_registry.get_text_connector("gemini_flash")

    assert isinstance(connector, root_gemini.GeminiGenAIConnector)
    assert not isinstance(connector, FailoverAIConnector)


def test_registry_returns_raw_gemini_when_fallback_disabled(
    monkeypatch: pytest.MonkeyPatch, patch_gemini_client: None
) -> None:
    """OPENAI_FALLBACK_ENABLED=false 면 키가 있어도 래핑하지 않는다(kill-switch)."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_FALLBACK_ENABLED", "false")

    connector = root_registry.get_text_connector("gemini_flash")

    assert isinstance(connector, root_gemini.GeminiGenAIConnector)
    assert not isinstance(connector, FailoverAIConnector)


def test_registry_does_not_wrap_non_gemini_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비-Gemini 커넥터(claude_sonnet)는 키가 있어도 폴백 래핑하지 않는다."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("CLAUDE_SONNET_API_KEY", "claude-key")

    connector = root_registry.get_text_connector("claude_sonnet")

    assert getattr(connector, "name", "") == "claude_sonnet"
    assert not isinstance(connector, FailoverAIConnector)


# --- OpenAIConnector.generate 의 chat.completions 매핑 검증 ---


@dataclass
class _ChatCall:
    model: str
    messages: list[dict[str, str]]
    temperature: float
    max_tokens: int
    extra: dict[str, object] = field(default_factory=dict)


class _FakeCompletions:
    def __init__(self, owner: "_FakeOpenAIClient") -> None:
        self._owner = owner

    async def create(self, *, model, messages, temperature, max_tokens, **extra):
        self._owner.calls.append(
            _ChatCall(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra=extra,
            )
        )
        message = SimpleNamespace(content="응답 본문")
        choice = SimpleNamespace(message=message, finish_reason="stop")
        usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7)
        return SimpleNamespace(choices=[choice], usage=usage)


class _FakeChat:
    def __init__(self, owner: "_FakeOpenAIClient") -> None:
        self.completions = _FakeCompletions(owner)


class _FakeOpenAIClient:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key
        self.calls: list[_ChatCall] = []
        self.chat = _FakeChat(self)

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_openai_connector_maps_request_to_chat_completions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """system/user/temperature/max_tokens 가 chat.completions 인자로 정확히 매핑된다."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_TEXT_MODEL", "gpt-test")
    monkeypatch.setattr(root_openai, "AsyncOpenAI", _FakeOpenAIClient)

    connector = OpenAIConnector()
    response = await connector.generate(
        ChapterAIRequest(system="시스템", user="사용자", max_tokens=128, temperature=0.3)
    )

    assert response.text == "응답 본문"
    assert response.model == "gpt-test"
    assert response.input_tokens == 11
    assert response.output_tokens == 7
    assert response.finish_reason == "stop"

    client = connector._client
    assert isinstance(client, _FakeOpenAIClient)
    call = client.calls[0]
    assert call.model == "gpt-test"
    assert call.temperature == 0.3
    assert call.max_tokens == 128
    assert call.messages == [
        {"role": "system", "content": "시스템"},
        {"role": "user", "content": "사용자"},
    ]


@pytest.mark.asyncio
async def test_openai_connector_omits_system_message_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """system 이 비어 있으면 system 메시지를 생략한다(Gemini system_instruction=None 동치)."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(root_openai, "AsyncOpenAI", _FakeOpenAIClient)

    connector = OpenAIConnector()
    await connector.generate(
        ChapterAIRequest(system="", user="사용자", max_tokens=64, temperature=0.0)
    )

    call = connector._client.calls[0]
    assert call.messages == [{"role": "user", "content": "사용자"}]


# --- max_tokens 모델 한도 클램프 검증 ---


def test_clamp_openai_max_tokens_caps_oversized_value() -> None:
    """Gemini 용 큰 값(32000)은 gpt-4o 상한(16384)으로 잘린다."""
    assert clamp_openai_max_tokens(32000, "gpt-4o") == 16384


def test_clamp_openai_max_tokens_keeps_value_under_cap() -> None:
    """상한 이하 값은 그대로 유지한다."""
    assert clamp_openai_max_tokens(8000, "gpt-4o") == 8000


def test_clamp_openai_max_tokens_uses_cap_when_none() -> None:
    """None 이면 모델 상한값을 그대로 사용한다."""
    assert clamp_openai_max_tokens(None, "gpt-4o") == 16384


def test_clamp_openai_max_tokens_uses_cap_when_non_positive() -> None:
    """0 이하 값도 모델 상한값으로 대체한다."""
    assert clamp_openai_max_tokens(0, "gpt-4o") == 16384


def test_clamp_openai_max_tokens_unknown_model_uses_safe_default() -> None:
    """미등록 모델은 안전 기본값(16384)으로 제한한다."""
    assert clamp_openai_max_tokens(32000, "gpt-unknown") == 16384


def test_clamp_openai_max_tokens_allows_higher_gpt5_cap() -> None:
    """gpt-5.x 는 더 큰 상한을 가져 32000 을 막지 않는다."""
    assert clamp_openai_max_tokens(32000, "gpt-5.5") == 32000


@pytest.mark.asyncio
async def test_openai_connector_clamps_oversized_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini 크기(32000) max_tokens 가 gpt-4o 상한(16384)으로 클램프되어 전달된다."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_TEXT_MODEL", "gpt-4o")
    monkeypatch.setattr(root_openai, "AsyncOpenAI", _FakeOpenAIClient)

    connector = OpenAIConnector()
    await connector.generate(
        ChapterAIRequest(system="시스템", user="사용자", max_tokens=32000, temperature=0.2)
    )

    call = connector._client.calls[0]
    assert call.max_tokens == 16384
