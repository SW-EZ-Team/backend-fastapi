"""AI 커넥터 브릿지 - 팩토리 및 공개 API.

개별 커넥터 구현은 _connector_*.py에 격리한다.
외부 모듈은 이 파일만 임포트하면 된다.

Gemini CLI 계열 커넥터는 테스트 전용이다. GEMINI_CLI_ENABLED=true 환경변수 없이
선택하면 RuntimeError를 발생시켜 프로덕션 선택을 차단한다.
"""
from __future__ import annotations

import asyncio
import contextvars
import inspect
import logging
import os
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
from app.modules.ExamForge_V1.common._connector_codex import CodexCliConnector
from app.modules.ExamForge_V1.common._connector_gemini import GeminiCliConnector
from app.modules.ExamForge_V1.common._connector_gemini import _clean_output as _gemini_clean_output
from app.modules.ExamForge_V1.common.config import (
    active_planner_model,
    active_text_model,
    active_verifier_model,
)

_LOG = logging.getLogger(__name__)

# Gemini CLI 선택을 막는 모델 이름 집합 (테스트 전용)
_GEMINI_MODEL_NAMES: frozenset[str] = frozenset({"gemini_cli_flash", "gemini_2_5_flash"})

# Anthropic 모델 이름 → 모델 ID 매핑
_ANTHROPIC_MODEL_MAP: dict[str, str] = {
    "opus46": "claude-opus-4-6",
    "claude_sonnet": "claude-sonnet-4-5-20250929",
}

# Gemini CLI 모델 이름 → 모델 ID 매핑
_GEMINI_CLI_MODEL_MAP: dict[str, str] = {
    "gemini_cli_flash": "gemini-2.5-flash",
    "gemini_2_5_flash": "gemini-2.5-flash",
}

_CONNECTOR_CACHE: dict[str, AIConnector] = {}
_current_budget = current_budget
_TaskResult = TypeVar("_TaskResult")


class _GeminiCliConnector:
    """기존 테스트가 참조하던 Gemini CLI 출력 정규화 호환 래퍼."""

    _clean_output = staticmethod(_gemini_clean_output)


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
    """이름으로 커넥터 인스턴스를 반환한다 (캐싱).

    Gemini CLI 커넥터는 테스트 전용이다. GEMINI_CLI_ENABLED=true 없이 선택하면
    RuntimeError를 발생시켜 프로덕션 선택을 차단한다.
    """
    if name in _CONNECTOR_CACHE:
        return _CONNECTOR_CACHE[name]

    # Gemini 선택 시 명시적 활성화 플래그를 요구한다
    if name in _GEMINI_MODEL_NAMES:
        enabled = os.getenv("GEMINI_CLI_ENABLED", "").strip().lower() == "true"
        if not enabled:
            raise RuntimeError(
                f"'{name}' 커넥터는 테스트 전용입니다. "
                "프로덕션에서 Gemini를 사용하려면 GEMINI_CLI_ENABLED=true 를 명시 설정하세요. "
                "프로덕션 기본 커넥터는 opus46 입니다."
            )
        _LOG.warning(
            "⚠️  Gemini CLI 커넥터(%s)가 선택되었습니다. "
            "이 커넥터는 테스트 전용입니다 — 프로덕션 환경에서 사용을 권장하지 않습니다.",
            name,
        )

    connector: AIConnector
    if name == "codex_cli":
        # Codex CLI 커넥터는 API 키 없이 ChatGPT OAuth를 사용한다
        connector = CodexCliConnector()
    elif name == "qwen27b_modal":
        connector = _Qwen27BModalExamForgeAdapter()
    elif name == "gemini_flash":
        connector = _build_gemini_genai_connector()
    elif name in _ANTHROPIC_MODEL_MAP:
        connector = AnthropicConnector(_ANTHROPIC_MODEL_MAP[name], name)
    elif name in _GEMINI_CLI_MODEL_MAP:
        connector = GeminiCliConnector(_GEMINI_CLI_MODEL_MAP[name], name)
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
    보유한 asyncio.Semaphore(generation_concurrency())로 위임되며,
    codex 전역 세마포어(max_concurrent=3)가 실 동시 codex 프로세스를 캡한다.
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


def _build_gemini_genai_connector() -> AIConnector:
    """google-genai SDK 커넥터는 선택 시점에만 로드한다."""
    from app.modules.ExamForge_V1.common._connector_gemini_genai import (
        GeminiGenAIConnector,
    )

    return GeminiGenAIConnector()


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
    "_GeminiCliConnector",
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
