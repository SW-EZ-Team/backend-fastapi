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

# Codex CLI — codex 바이너리가 없는 환경에서도 다른 커넥터는 정상 동작하도록 보호
try:
    from .text.codex_cli_connector import CodexCLIConnector
    CONNECTORS["codex_cli"] = lambda: CodexCLIConnector()
except ImportError as _codex_import_err:
    _LOG.warning(
        "Codex CLI 커넥터 등록 건너뜀 (ImportError: %s).",
        _codex_import_err,
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
    return CONNECTORS[name]()


def get_text_connector(model_name: str | None = None) -> AIConnector:
    """.env 의 ACTIVE_TEXT_MODEL 또는 명시된 model_name 으로 텍스트 커넥터 반환.

    ACTIVE_TEXT_MODEL=claude_sonnet  → ClaudeSonnetConnector
    ACTIVE_TEXT_MODEL=codex_cli      → CodexCLIConnector
    기본값: claude_sonnet

    관리자가 .env 값 하나만 바꾸면 즉시 커넥터가 교체된다.
    """
    name = model_name or os.getenv("ACTIVE_TEXT_MODEL", "claude_sonnet")
    if name not in CONNECTORS:
        raise ModelNotFoundError(
            f"Unknown text model: {name}. "
            f"Registered: {list(CONNECTORS.keys())}. "
            f"ACTIVE_TEXT_MODEL 환경변수와 anthropic 패키지 설치를 확인하세요."
        )
    return CONNECTORS[name]()
