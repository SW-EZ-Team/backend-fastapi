"""google-genai Gemini 텍스트 커넥터 오프라인 단위 테스트."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pytest
from google.genai import errors as genai_errors

from ai_connectors import _gemini_throttle
from ai_connectors import _registry_text as root_registry
from ai_connectors.errors import AuthError as RootAuthError
from ai_connectors.errors import RateLimitError as RootRateLimitError
from ai_connectors.text import gemini_connector as root_gemini
from ai_connectors.text_schemas import ChapterAIRequest as RootRequest
from app.modules.ChapterStudio_V1.ai_connectors import registry as chapter_registry
from app.modules.ChapterStudio_V1.ai_connectors import gemini_genai_connector as chapter_gemini
from app.modules.ChapterStudio_V1.ai_connectors.schemas import (
    ChapterAIRequest as ChapterRequest,
)
from app.modules.ExamForge_V1.common import ai_bridge as exam_bridge
from app.modules.ExamForge_V1.common import _connector_gemini_genai as exam_gemini
from app.modules.ExamForge_V1.common._ai_schemas import (
    ChapterAIRequest as ExamRequest,
    LLMBudgetCounter,
)


@dataclass
class _Call:
    model: str
    contents: str
    config: object


class _Usage:
    prompt_token_count = 12
    candidates_token_count = 8


class _Candidate:
    finish_reason = "STOP"


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.usage_metadata = _Usage()
        self.candidates = [_Candidate()]


class _FakeModels:
    def __init__(self, owner: "_FakeClient") -> None:
        self._owner = owner

    def generate_content(self, *, model: str, contents: str, config: object) -> _FakeResponse:
        self._owner.calls.append(_Call(model=model, contents=contents, config=config))
        if _FakeClient.errors:
            raise _FakeClient.errors.pop(0)
        return _FakeResponse(_FakeClient.response_text)


class _FakeClient:
    last: ClassVar["_FakeClient | None"] = None
    response_text: ClassVar[str] = "<think>추론</think>\n본문"
    errors: ClassVar[list[BaseException]] = []

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.calls: list[_Call] = []
        self.models = _FakeModels(self)
        _FakeClient.last = self

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def reset_fake_client() -> None:
    """테스트마다 가짜 클라이언트 상태를 초기화한다."""
    _FakeClient.last = None
    _FakeClient.response_text = "<think>추론</think>\n본문"
    _FakeClient.errors = []


@pytest.fixture(autouse=True)
def stabilization_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini 안정화 환경을 테스트 기본값으로 고정한다.

    스로틀/백오프 대기를 0으로 만들고, 모델 폴백 체인을 단일 모델로 제한하며,
    .env(dotenv import 부수효과)로 주입된 프로바이더 폴백 키가 레지스트리
    래핑 동작을 바꾸지 않도록 제거한다.
    """
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "0")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_ATTEMPTS", "3")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_INITIAL_MS", "0")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_MAX_MS", "0")
    monkeypatch.setenv("GEMINI_TEXT_MODEL_FALLBACKS", "gemini-test")
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_FALLBACK_ENABLED",
        "ANTHROPIC_API_KEY",
        "CLAUDE_SONNET_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    _gemini_throttle.reset_throttle()


def _patch_client(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    monkeypatch.setattr(getattr(module, "genai"), "Client", _FakeClient)


def _assert_common_call(call: _Call) -> None:
    assert call.model == "gemini-test"
    assert call.contents == "사용자"
    assert getattr(call.config, "system_instruction") == "시스템"
    assert getattr(call.config, "temperature") == 0.3
    assert getattr(call.config, "max_output_tokens") == 128


@pytest.mark.asyncio
async def test_root_gemini_generate_passes_model_temperature_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "root-key")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")
    _patch_client(monkeypatch, root_gemini)

    connector = root_gemini.GeminiGenAIConnector()
    response = await connector.generate(
        RootRequest(system="시스템", user="사용자", max_tokens=128, temperature=0.3)
    )

    assert response.text == "본문"
    assert response.model == "gemini-test"
    assert response.input_tokens == 12
    assert response.output_tokens == 8
    assert _FakeClient.last is not None
    _assert_common_call(_FakeClient.last.calls[0])


def test_root_gemini_rejects_empty_google_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RootAuthError):
        root_gemini.GeminiGenAIConnector()


def test_root_gemini_accepts_gemini_api_key_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")
    _patch_client(monkeypatch, root_gemini)

    connector = root_gemini.GeminiGenAIConnector()

    assert connector.name == "gemini_flash"
    assert _FakeClient.last is not None
    assert _FakeClient.last.api_key == "gemini-key"


def test_module_gemini_connectors_accept_gemini_api_key_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")

    _patch_client(monkeypatch, chapter_gemini)
    chapter_connector = chapter_gemini.GeminiGenAIConnector()
    assert chapter_connector.name == "gemini_flash"
    assert _FakeClient.last is not None
    assert _FakeClient.last.api_key == "gemini-key"

    _patch_client(monkeypatch, exam_gemini)
    exam_connector = exam_gemini.GeminiGenAIConnector()
    assert exam_connector.name == "gemini_flash"
    assert _FakeClient.last is not None
    assert _FakeClient.last.api_key == "gemini-key"


@pytest.mark.asyncio
async def test_root_gemini_normalizes_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "root-key")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")
    _patch_client(monkeypatch, root_gemini)
    _FakeClient.errors = [
        genai_errors.ClientError(429, {"error": {"message": "quota"}})
        for _ in range(3)
    ]

    connector = root_gemini.GeminiGenAIConnector()
    with pytest.raises(RootRateLimitError):
        await connector.generate(
            RootRequest(system="시스템", user="사용자", max_tokens=128, temperature=0.3)
        )


def test_root_registry_returns_gemini_flash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "root-key")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")
    _patch_client(monkeypatch, root_gemini)

    connector = root_registry.get_text_connector("gemini_flash")

    assert isinstance(connector, root_gemini.GeminiGenAIConnector)


@pytest.mark.asyncio
async def test_chapter_gemini_generate_and_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "chapter-key")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")
    _patch_client(monkeypatch, chapter_gemini)
    chapter_registry.clear_cache()

    connector = chapter_registry.get_connector("gemini_flash")
    assert isinstance(connector, chapter_gemini.GeminiGenAIConnector)
    assert not connector.supports("batch")
    response = await connector.generate(
        ChapterRequest(system="시스템", user="사용자", max_tokens=128, temperature=0.3)
    )

    assert response.text == "본문"
    assert _FakeClient.last is not None
    _assert_common_call(_FakeClient.last.calls[0])


@pytest.mark.asyncio
async def test_examforge_gemini_generate_budget_retry_and_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "exam-key")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")
    monkeypatch.setenv("ACTIVE_TEXT_MODEL", "gemini_flash")
    monkeypatch.delenv("ACTIVE_VERIFIER_MODEL", raising=False)
    _patch_client(monkeypatch, exam_gemini)
    exam_bridge._CONNECTOR_CACHE.clear()
    _FakeClient.errors = [genai_errors.ServerError(503, {"error": {"message": "busy"}})]

    connector = exam_bridge.get_text_connector()
    assert exam_bridge.get_verifier_connector() is connector
    budget = LLMBudgetCounter(budget=2)
    response = await connector.generate(
        ExamRequest(system="시스템", user="사용자", max_tokens=128, temperature=0.3),
        budget=budget,
    )

    assert isinstance(connector, exam_gemini.GeminiGenAIConnector)
    assert response.text == "본문"
    assert budget.count == 1
    assert _FakeClient.last is not None
    assert len(_FakeClient.last.calls) == 2
    _assert_common_call(_FakeClient.last.calls[-1])
