"""텍스트 생성 커넥터 서브레지스트리.

CONNECTORS dict 와 get_connector / get_text_connector 팩토리를 담는다.
외부 코드는 이 파일을 직접 import 하지 않고 ai_connectors.registry 를 사용한다.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

from .base import AIConnector
from .errors import ModelNotFoundError

_LOG = logging.getLogger(__name__)

# 텍스트 생성 커넥터 팩토리 맵 (AIConnector 구현체)
# ACTIVE_TEXT_MODEL 또는 AI_MODEL(.env) 으로 선택
CONNECTORS: dict[str, Callable[[], AIConnector]] = {}

# Claude Sonnet — Anthropic SDK 미설치 환경에서도 다른 커넥터는 정상 동작하도록 보호
try:
    from .text.claude_sonnet_connector import ClaudeSonnetConnector
    CONNECTORS["claude_sonnet"] = lambda: ClaudeSonnetConnector()
except ImportError as _claude_import_err:
    _LOG.warning(
        "Claude Sonnet 커넥터 등록 건너뜀 (ImportError: %s). "
        "`uv pip install anthropic` 실행 필요",
        _claude_import_err,
    )

# Gemini Flash — google-genai 미설치 환경에서도 다른 커넥터는 정상 동작하도록 보호
try:
    from .text.gemini_connector import GeminiGenAIConnector
    CONNECTORS["gemini_flash"] = lambda: GeminiGenAIConnector()
except ImportError as _gemini_import_err:
    _LOG.warning(
        "Gemini Flash 커넥터 등록 건너뜀 (ImportError: %s). "
        "`uv pip install google-genai` 실행 필요",
        _gemini_import_err,
    )

def _build_fallback_factories() -> list[Callable[[], AIConnector]]:
    """Gemini 폴백 체인 팩토리 목록을 만든다 — OpenAI → Claude Sonnet 순.

    - OpenAI : OPENAI_API_KEY 존재 + OPENAI_FALLBACK_ENABLED!=false 일 때만 포함.
    - Claude : CLAUDE_SONNET_API_KEY 또는 ANTHROPIC_API_KEY 존재 시 포함.
    SDK 미설치(ImportError)는 해당 항목만 건너뛴다.
    """
    from common.text_config import (
        claude_sonnet_api_key,
        openai_api_key,
        openai_fallback_enabled,
    )

    factories: list[Callable[[], AIConnector]] = []
    if openai_fallback_enabled() and openai_api_key() is not None:
        try:
            from .text.openai_connector import OpenAIConnector

            factories.append(lambda: OpenAIConnector())
        except ImportError as exc:
            _LOG.warning(
                "OpenAI 텍스트 폴백 제외 (ImportError: %s). `uv add openai` 실행 필요",
                exc,
            )
    if claude_sonnet_api_key() is not None:
        try:
            from .text.claude_sonnet_connector import ClaudeSonnetConnector

            factories.append(lambda: ClaudeSonnetConnector())
        except ImportError as exc:
            _LOG.warning(
                "Claude 텍스트 폴백 제외 (ImportError: %s). "
                "`uv pip install anthropic` 실행 필요",
                exc,
            )
    return factories


def _wrap_with_openai_failover(connector: AIConnector) -> AIConnector:
    """선택된 커넥터가 Gemini 이면 OpenAI → Claude 폴백 체인 래퍼로 감싼다.

    활성 조건: 커넥터가 gemini_flash + 폴백 후보(OpenAI/Claude 키)가 1개 이상.
    그 외에는 원본 커넥터를 그대로 반환한다(기존 동작 보존).
    폴백이 AuthError(무효 키)를 올리면 그 폴백만 영구 제외하고 다음으로 넘어간다.
    """
    from common.text_config import text_fallback_after_failures

    if getattr(connector, "name", "") != "gemini_flash":
        return connector
    factories = _build_fallback_factories()
    if not factories:
        return connector
    try:
        from ._failover_text import FailoverAIConnector
    except ImportError as exc:
        _LOG.warning("텍스트 폴백 래핑 건너뜀 (ImportError: %s)", exc)
        return connector
    return FailoverAIConnector(
        primary=connector,
        fallback_factories=factories,
        name="gemini_text_failover",
        failure_threshold=text_fallback_after_failures(),
    )


def get_connector(model_name: str | None = None) -> AIConnector:
    """.env 의 AI_MODEL 또는 명시된 model_name 으로 텍스트 커넥터 반환."""
    name = model_name or os.getenv("AI_MODEL")
    if not name:
        raise ModelNotFoundError("AI_MODEL is not set in .env and no model_name given")
    if name not in CONNECTORS:
        raise ModelNotFoundError(
            f"Unknown model: {name}. Registered: {list(CONNECTORS.keys())}"
        )
    return _wrap_with_openai_failover(CONNECTORS[name]())


def get_text_connector(model_name: str | None = None) -> AIConnector:
    """.env 의 ACTIVE_TEXT_MODEL 또는 명시된 model_name 으로 텍스트 커넥터 반환.

    ACTIVE_TEXT_MODEL=claude_sonnet  → ClaudeSonnetConnector
    ACTIVE_TEXT_MODEL=gemini_flash   → GeminiGenAIConnector (활성 기본 경로)
    기본값: claude_sonnet

    Gemini 가 선택되고 OPENAI_API_KEY 가 있으면 OpenAI 폴백 래퍼로 자동 감싼다.
    관리자가 .env 값 하나만 바꾸면 즉시 커넥터가 교체된다.
    """
    name = model_name or os.getenv("ACTIVE_TEXT_MODEL", "claude_sonnet")
    if name not in CONNECTORS:
        raise ModelNotFoundError(
            f"Unknown text model: {name}. "
            f"Registered: {list(CONNECTORS.keys())}. "
            f"ACTIVE_TEXT_MODEL 환경변수와 커넥터 의존성 설치를 확인하세요."
        )
    return _wrap_with_openai_failover(CONNECTORS[name]())
