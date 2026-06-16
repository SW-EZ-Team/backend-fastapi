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
    active_grading_model,
    active_planner_model,
    active_text_model,
    active_verifier_model,
    claude_sonnet_api_key,
    openai_api_key,
    openai_fallback_enabled,
)
from app.modules.ExamForge_V1.common.errors import AuthError, ConnectorError

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

    async def generate(
        self,
        req: ChapterAIRequest,
        budget: LLMBudgetCounter | None = None,
    ) -> ChapterAIResponse:
        """동일 필드 스키마를 ExamForge 응답 타입으로 되돌린다.

        다른 커넥터(anthropic/gemini)와 동일한 예산 계약을 따른다: budget 인자가
        없으면 current_budget contextvar에서 읽고, 호출 전 check()/성공 후 increment()
        로 시험당 하드 상한을 강제한다. 이 배선이 없으면 ACTIVE_TEXT_MODEL=qwen27b_modal
        인 Modal 배포 경로에서만 예산 카운터를 우회해 비용 폭주가 가능했다(2026-06-13 감사).
        """
        from app.modules.ChapterStudio_V1.ai_connectors.schemas import (
            ChapterAIRequest as StudioAIRequest,
        )

        if budget is None:
            budget = current_budget.get()
        if budget is not None:
            budget.check()

        studio_req = StudioAIRequest(
            system=req.system,
            user=req.user,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            extra=req.extra,
        )
        resp = await self._connector.generate(studio_req)
        if budget is not None:
            budget.increment()
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
    """Gemini 텍스트 실패 시 OpenAI → Claude Sonnet 순으로 넘기는 ExamForge 폴백 래퍼.

    매 호출마다 primary(Gemini)를 먼저 시도하고 ConnectorError 계열이면 폴백 체인을
    순서대로 한 번씩 시도한다 — 요청 간 sticky 상태 없음(다음 요청은 다시 primary부터).
    AuthError(키 무효/미설정) 단계는 영구 제외하고 다음 단계로 진행한다.
    budget 카운터는 각 커넥터가 내부에서 check/increment 하므로 그대로 전달만 한다.
    """

    name: str = "gemini_openai_fallback"

    def __init__(
        self,
        primary: AIConnector,
        fallback_factory: Callable[[], AIConnector] | None = None,
        *,
        fallback_factories: Sequence[Callable[[], AIConnector]] | None = None,
    ) -> None:
        # 하위 호환: 단일 fallback_factory는 길이 1짜리 체인으로 흡수한다
        if fallback_factories is None:
            if fallback_factory is None:
                raise ValueError("fallback_factory 또는 fallback_factories 가 필요하다.")
            fallback_factories = (fallback_factory,)
        elif fallback_factory is not None:
            raise ValueError("fallback_factory 와 fallback_factories 는 동시에 줄 수 없다.")
        self._primary = primary
        self._fallback_factories: list[Callable[[], AIConnector]] = list(fallback_factories)
        self._fallbacks: list[AIConnector | None] = [None] * len(self._fallback_factories)
        # AuthError/생성 실패로 영구 제외된 폴백 인덱스
        self._skipped: set[int] = set()

    async def generate(
        self,
        req: ChapterAIRequest,
        budget: LLMBudgetCounter | None = None,
    ) -> ChapterAIResponse:
        from app.modules.ExamForge_V1.common import _provider_health as health

        last_error: Exception = ConnectorError("폴백 체인 진입")
        primary_name = getattr(self._primary, "name", "")
        skip_primary = primary_name == "gemini_flash" and health.is_exhausted("gemini_flash")

        if not skip_primary:
            try:
                return await self._primary.generate(req, budget)
            except ConnectorError as exc:
                last_error = exc
        else:
            _LOG.info(
                "%s: gemini_flash 소진 기록 — OpenAI→Claude 폴백 체인으로 바로 진행",
                self.name,
            )

        for index in range(len(self._fallback_factories)):
            connector = self._connector_at(index)
            if connector is None:
                continue
            stage_name = getattr(connector, "name", "fallback")
            if health.is_exhausted(stage_name):
                _LOG.debug("%s: 폴백 %s 소진 기록 — 단계 건너뜀", self.name, stage_name)
                continue
            try:
                response = await connector.generate(req, budget)
                _LOG.info("%s: 폴백 %s 성공", self.name, stage_name)
                return response
            except AuthError as exc:
                # 인증 실패 단계는 영구 제외하고 다음 단계로 넘어간다.
                self._skipped.add(index)
                last_error = exc
                _LOG.warning(
                    "%s: 폴백 %s AuthError — 영구 제외하고 다음 단계 진행: %s",
                    self.name,
                    stage_name,
                    exc,
                )
            except ConnectorError as exc:
                last_error = exc
                _LOG.warning(
                    "%s: 폴백 %s 실패 — 다음 단계 시도: %s",
                    self.name,
                    stage_name,
                    exc,
                )
            except RuntimeError as exc:
                # Anthropic 커넥터 생성/호출 실패가 RuntimeError 로 올라오는 경로 흡수.
                last_error = ConnectorError(str(exc))
                _LOG.warning(
                    "%s: 폴백 %s RuntimeError — 다음 단계 시도: %s",
                    self.name,
                    stage_name,
                    exc,
                )
        # 전 단계 실패 — 마지막 에러를 그대로 드러낸다(조용한 빈 응답 금지).
        raise last_error

    def _connector_at(self, index: int) -> AIConnector | None:
        """index 단계 커넥터를 지연 생성한다. 생성 실패(키 누락 등)는 단계만 제외한다."""
        if index in self._skipped:
            return None
        connector = self._fallbacks[index]
        if connector is None:
            try:
                connector = self._fallback_factories[index]()
            except (ConnectorError, RuntimeError) as exc:
                # AnthropicConnector 는 키 누락 시 RuntimeError 를 올린다 — 해당 단계만 제외.
                self._skipped.add(index)
                _LOG.warning(
                    "%s: 폴백 커넥터 생성 실패(index=%d) — 영구 제외: %s",
                    self.name,
                    index,
                    exc,
                )
                return None
            self._fallbacks[index] = connector
        return connector

    def supports(self, feature: str) -> bool:
        if feature == "fallback":
            return True
        return self._primary.supports(feature)


def _build_gemini_genai_connector() -> AIConnector:
    """google-genai SDK 커넥터는 선택 시점에만 로드한다.

    폴백 체인은 OpenAI → Claude Sonnet 순이다(키 있는 단계만 포함):
    - OpenAI : OPENAI_API_KEY 존재 + OPENAI_FALLBACK_ENABLED!=false 일 때만.
    - Claude : CLAUDE_SONNET_API_KEY 또는 ANTHROPIC_API_KEY 존재 시.
    후보가 하나도 없으면 raw Gemini 커넥터를 그대로 반환한다(기존 동작 보존).
    """
    from app.modules.ExamForge_V1.common._connector_gemini_genai import (
        GeminiGenAIConnector,
    )

    gemini = GeminiGenAIConnector()
    factories = _fallback_stage_factories()
    if not factories:
        return gemini
    return _OpenAIFailoverConnector(gemini, fallback_factories=factories)


def _fallback_stage_factories() -> list[Callable[[], AIConnector]]:
    """Gemini 폴백 단계 팩토리 목록을 만든다 — OpenAI → Claude Sonnet 순.

    SDK 미설치(ImportError)는 해당 단계만 건너뛴다.
    """
    factories: list[Callable[[], AIConnector]] = []
    if openai_fallback_enabled() and openai_api_key() is not None:
        try:
            from app.modules.ExamForge_V1.common._connector_openai import OpenAIConnector

            factories.append(OpenAIConnector)
        except ImportError:
            pass
    if claude_sonnet_api_key() is not None:
        factories.append(
            lambda: AnthropicConnector(_ANTHROPIC_MODEL_MAP["claude_sonnet"], "claude_sonnet")
        )
    return factories


def active_text_provider_chain() -> list[str]:
    """현재 활성 텍스트 경로가 실제로 시도하는 프로바이더 이름 체인을 반환한다.

    사전점검(생성 전 전 프로바이더 소진 여부 판단)이 "어떤 프로바이더들이 살아있어야
    하는가"를 subject-agnostic 하게 알기 위한 단일 진실원천이다.

    - active_text_model() 이 gemini_flash 면 폴백 래퍼 체인(gemini_flash → OpenAI →
      claude_sonnet, 키 있는 단계만)을 그대로 반영한다.
    - 그 외(opus46/claude_sonnet/qwen27b_modal 등)는 단일 프로바이더 체인이다.

    실제 _build_gemini_genai_connector 와 동일한 키 가용성 규칙을 재사용해
    "코드가 진짜로 시도하는 단계"만 체인에 넣는다(거짓 차단 방지).
    """
    name = active_text_model()
    if name != "gemini_flash":
        return [name]
    chain = ["gemini_flash"]
    if openai_fallback_enabled() and openai_api_key() is not None:
        chain.append("openai_text")
    if claude_sonnet_api_key() is not None:
        chain.append("claude_sonnet")
    return chain


def text_providers_all_exhausted() -> bool:
    """활성 텍스트 프로바이더 체인이 비어있지 않고 전부 소진 상태면 True.

    생성 전 사전점검의 단일 판정 함수다. 하나라도 살아있으면(또는 체인을 알 수 없으면)
    False 를 돌려 정상 생성을 절대 막지 않는다(거짓 차단 금지).
    """
    from app.modules.ExamForge_V1.common import _provider_health as health

    return health.all_exhausted(active_text_provider_chain())


def get_text_connector() -> AIConnector:
    """텍스트 생성 커넥터를 반환한다."""
    return get_connector(active_text_model())


def get_planner_connector() -> AIConnector:
    """계획 수립 커넥터를 반환한다."""
    return get_connector(active_planner_model())


def get_verifier_connector() -> AIConnector:
    """정답 검증 커넥터를 반환한다."""
    return get_connector(active_verifier_model())


# 채점/총평 전용 커넥터 캐시 — 텍스트 생성 캐시(_CONNECTOR_CACHE)와 분리한다.
_GRADING_CONNECTOR_CACHE: dict[str, AIConnector] = {}


def get_grading_connector() -> AIConnector:
    """모의고사 채점/총평 전용 커넥터를 반환한다.

    기본은 claude_sonnet(Claude Sonnet)이며, 사용한도 소진 등으로 Claude가 즉시 실패하면
    gemini_flash로 폴백해 라이브 채점이 하드페일하지 않게 한다(폴백 시 WARNING 로깅).
    ACTIVE_GRADING_MODEL로 다른 커넥터를 지정하면 그 커넥터를 단일 체인으로 쓴다.
    """
    name = active_grading_model()
    cached = _GRADING_CONNECTOR_CACHE.get(name)
    if cached is not None:
        return cached
    if name == "claude_sonnet":
        primary = get_connector("claude_sonnet")
        # gemini 폴백은 키/SDK 가용할 때만 실제로 붙는다(생성 실패 단계는 자동 제외).
        connector: AIConnector = _OpenAIFailoverConnector(
            primary,
            fallback_factories=[lambda: get_connector("gemini_flash")],
        )
    else:
        connector = get_connector(name)
    _GRADING_CONNECTOR_CACHE[name] = connector
    return connector


__all__ = [
    "ChapterAIRequest",
    "ChapterAIResponse",
    "AIConnector",
    "LLMBudgetCounter",
    "_current_budget",
    "get_connector",
    "get_current_budget",
    "get_grading_connector",
    "get_planner_connector",
    "get_text_connector",
    "get_verifier_connector",
    "active_text_provider_chain",
    "text_providers_all_exhausted",
    "connector_supports_batch",
    "run_connector_tasks",
    "set_current_budget",
    "set_allow_reserve",
    "get_allow_reserve",
]
