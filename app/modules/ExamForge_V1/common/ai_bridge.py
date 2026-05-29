"""AI 커넥터 브릿지 - 팩토리 및 공개 API.

개별 커넥터 구현은 _connector_*.py에 격리한다.
외부 모듈은 이 파일만 임포트하면 된다.

Gemini 계열 커넥터는 테스트 전용이다. GEMINI_CLI_ENABLED=true 환경변수 없이
선택하면 RuntimeError를 발생시켜 프로덕션 선택을 차단한다.
"""
from __future__ import annotations

import contextvars
import logging
import os

_LOG = logging.getLogger(__name__)

# Gemini 선택을 막는 모델 이름 집합 (테스트 전용)
_GEMINI_MODEL_NAMES: frozenset[str] = frozenset({"gemini_cli_flash", "gemini_2_5_flash"})

from app.modules.ExamForge_V1.common._ai_schemas import (
    AIConnector,
    ChapterAIRequest,
    ChapterAIResponse,
    LLMBudgetCounter,
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


class _GeminiCliConnector:
    """기존 테스트가 참조하던 Gemini CLI 출력 정규화 호환 래퍼."""

    _clean_output = staticmethod(_gemini_clean_output)


def set_current_budget(budget: LLMBudgetCounter) -> contextvars.Token:
    """현재 파이프라인 실행의 예산 카운터를 설정한다."""
    return current_budget.set(budget)


def get_current_budget() -> LLMBudgetCounter | None:
    """현재 파이프라인 실행의 예산 카운터를 반환한다."""
    return current_budget.get()


def get_connector(name: str) -> AIConnector:
    """이름으로 커넥터 인스턴스를 반환한다 (캐싱).

    Gemini 계열 커넥터는 테스트 전용이다. GEMINI_CLI_ENABLED=true 없이 선택하면
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
    elif name in _ANTHROPIC_MODEL_MAP:
        connector = AnthropicConnector(_ANTHROPIC_MODEL_MAP[name], name)
    elif name in _GEMINI_CLI_MODEL_MAP:
        connector = GeminiCliConnector(_GEMINI_CLI_MODEL_MAP[name], name)
    else:
        raise RuntimeError(f"'{name}' 커넥터가 등록되지 않았다.")

    _CONNECTOR_CACHE[name] = connector
    return connector


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
    "set_current_budget",
]
