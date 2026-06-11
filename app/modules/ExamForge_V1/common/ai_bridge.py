"""AI 커넥터 브릿지 - 팩토리 및 공개 API.

개별 커넥터 구현은 _connector_*.py에 격리한다.
외부 모듈은 이 파일만 임포트하면 된다.

활성 텍스트 경로는 gemini_flash(google-genai SDK)이며, anthropic(opus46/claude_sonnet)과
qwen27b_modal 은 배포·폴백용으로 보존한다.
"""
from __future__ import annotations

import asyncio
import contextvars
import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from app.modules.ExamForge_V1.common._ai_schemas import (
    AIConnector,
    ChapterAIRequest,
    ChapterAIResponse,
    LLMBudgetCounter,
    allow_reserve_budget,
    current_budget,
)
from app.modules.ExamForge_V1.common._connector_anthropic import AnthropicConnector
from app.modules.ExamForge_V1.common.config import (
    active_planner_model,
    active_text_model,
    active_verifier_model,
    openai_api_key,
    openai_fallback_enabled,
)
from app.modules.ExamForge_V1.common.errors import ConnectorError

_LOG = logging.getLogger(__name__)

# Anthropic 모델 이름 → 모델 ID 매핑
_ANTHROPIC_MODEL_MAP: dict[str, str] = {
    "opus46": "claude-opus-4-6",
    "claude_sonnet": "claude-sonnet-4-6",
}

_CONNECTOR_CACHE: dict[str, AIConnector] = {}
_current_budget = current_budget
_TaskResult = TypeVar("_TaskResult")


class _Qwen27BModalExamForgeAdapter:
    """ChapterStudio Modal 커넥터를 ExamForge 스키마로 감싸는 어댑터."""

    name: str = "qwen27b_modal"

    def __init__(self) -> None:
        from app.modules.ChapterStudio_V1.ai_connectors.qwen27b_modal_connector import (
            Qwen27BModalConnector,
        )

        self._connector: Qwen27BModalConnector = Qwen27BModalConnector()

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """동일 필드 스키마를 ExamForge 응답 타입으로 되돌린다."""
        from app.modules.ChapterStudio_V1.ai_connectors.schemas import (
            ChapterAIRequest as StudioAIRequest,
        )

        studio_req = StudioAIRequest(
            system=req.system,
            user=req.user,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            extra=req.extra,
        )
        resp = await self._connector.generate(studio_req)
        return ChapterAIResponse(
            text=resp.text,
            model=resp.model,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            finish_reason=resp.finish_reason,
        )

    def supports(self, feature: str) -> bool:
        """Modal B200 경로는 문항별 병렬 실행을 허용한다."""
        if feature == "batch":
            return True
        return self._connector.supports(feature)


def set_current_budget(budget: LLMBudgetCounter) -> contextvars.Token:
    """현재 파이프라인 실행의 예산 카운터를 설정한다."""
    return current_budget.set(budget)


def get_current_budget() -> LLMBudgetCounter | None:
    """현재 파이프라인 실행의 예산 카운터를 반환한다."""
    return current_budget.get()


def set_allow_reserve(value: bool) -> contextvars.Token:
    """해설 생성 구간에서 reserve 예산 사용을 허용/해제한다."""
    return allow_reserve_budget.set(value)


def get_allow_reserve() -> bool:
    """현재 호출이 reserve 예산을 끌어쓸 수 있는지 반환한다."""
    return allow_reserve_budget.get()


def get_connector(name: str) -> AIConnector:
    """이름으로 커넥터 인스턴스를 반환한다 (캐싱)."""
    if name in _CONNECTOR_CACHE:
        return _CONNECTOR_CACHE[name]

    connector: AIConnector
    if name == "qwen27b_modal":
        connector = _Qwen27BModalExamForgeAdapter()
    elif name == "gemini_flash":
        connector = _build_gemini_genai_connector()
    elif name in _ANTHROPIC_MODEL_MAP:
        connector = AnthropicConnector(_ANTHROPIC_MODEL_MAP[name], name)
    else:
        raise RuntimeError(f"'{name}' 커넥터가 등록되지 않았다.")

    _CONNECTOR_CACHE[name] = connector
    return connector


async def run_connector_tasks(
    task_factories: Sequence[Callable[[], Awaitable[_TaskResult]]],
    connector: AIConnector,
) -> list[_TaskResult | Exception]:
    """항상 asyncio.gather로 병렬 실행한다.

    batch 지원 여부와 무관하게 병렬 실행한다. 동시성 제한은 각 팩토리가
    보유한 asyncio.Semaphore(generation_concurrency())로 위임된다.
    순서 정합은 gather가 입력 순서대로 결과를 반환하므로 보장된다.
    예산 카운터 원자성은 단일 이벤트 루프 + await 경계 없는 check/increment로 유지된다.
    """
    return list(
        await asyncio.gather(
            *(factory() for factory in task_factories),
            return_exceptions=True,
        )
    )


def connector_supports_batch(connector: AIConnector) -> bool:
    """동기 supports 계약만 batch 지원으로 인정한다."""
    supported = connector.supports("batch")
    if inspect.isawaitable(supported):
        closer = getattr(supported, "close", None)
        if callable(closer):
            closer()
        return False
    return supported is True


class _OpenAIFailoverConnector:
    """Gemini 텍스트 실패 시 OpenAI 로 넘기는 ExamForge 폴백 래퍼.

    매 호출마다 primary(Gemini)를 먼저 시도하고 ConnectorError 계열이면
    fallback(OpenAI)으로 한 번 재시도한다. budget 카운터는 각 커넥터가
    내부에서 check/increment 하므로 그대로 전달만 한다.
    """

    name: str = "gemini_openai_fallback"

    def __init__(
        self,
        primary: AIConnector,
        fallback_factory: Callable[[], AIConnector],
    ) -> None:
        self._primary = primary
        self._fallback_factory = fallback_factory
        self._fallback: AIConnector | None = None

    async def generate(
        self,
        req: ChapterAIRequest,
        budget: LLMBudgetCounter | None = None,
    ) -> ChapterAIResponse:
        try:
            return await self._primary.generate(req, budget)
        except ConnectorError:
            return await self._fallback_connector().generate(req, budget)

    def _fallback_connector(self) -> AIConnector:
        if self._fallback is None:
            self._fallback = self._fallback_factory()
        return self._fallback

    def supports(self, feature: str) -> bool:
        if feature == "fallback":
            return True
        return self._primary.supports(feature)


def _build_gemini_genai_connector() -> AIConnector:
    """google-genai SDK 커넥터는 선택 시점에만 로드한다.

    OPENAI_API_KEY 가 있고 OPENAI_FALLBACK_ENABLED!=false 면 OpenAI 폴백 래퍼로 감싼다.
    """
    from app.modules.ExamForge_V1.common._connector_gemini_genai import (
        GeminiGenAIConnector,
    )

    gemini = GeminiGenAIConnector()
    if not openai_fallback_enabled() or openai_api_key() is None:
        return gemini
    try:
        from app.modules.ExamForge_V1.common._connector_openai import OpenAIConnector
    except ImportError:
        return gemini
    return _OpenAIFailoverConnector(gemini, OpenAIConnector)


def get_text_connector() -> AIConnector:
    """텍스트 생성 커넥터를 반환한다."""
    return get_connector(active_text_model())


def get_planner_connector() -> AIConnector:
    """계획 수립 커넥터를 반환한다."""
    return get_connector(active_planner_model())


def get_verifier_connector() -> AIConnector:
    """정답 검증 커넥터를 반환한다."""
    return get_connector(active_verifier_model())


__all__ = [
    "ChapterAIRequest",
    "ChapterAIResponse",
    "AIConnector",
    "LLMBudgetCounter",
    "_current_budget",
    "get_connector",
    "get_current_budget",
    "get_planner_connector",
    "get_text_connector",
    "get_verifier_connector",
    "connector_supports_batch",
    "run_connector_tasks",
    "set_current_budget",
    "set_allow_reserve",
    "get_allow_reserve",
]
