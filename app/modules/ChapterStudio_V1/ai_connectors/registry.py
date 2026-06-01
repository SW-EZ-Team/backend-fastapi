from __future__ import annotations

import logging
import os
from typing import Protocol, runtime_checkable

from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector, TTSConnector

from app.modules.ChapterStudio_V1.ai_connectors.claude_sonnet_connector import ClaudeSonnetConnector
from app.modules.ChapterStudio_V1.ai_connectors.codex_cli_connector import CodexCLIConnector
from app.modules.ChapterStudio_V1.ai_connectors.failover_connector import FailoverAIConnector
from app.modules.ChapterStudio_V1.ai_connectors.errors import ModelNotFoundError
from app.modules.ChapterStudio_V1.ai_connectors.gemini_cli_connector import GeminiCLIConnector
from app.modules.ChapterStudio_V1.ai_connectors.kanana2_connector import Kanana2Connector
from app.modules.ChapterStudio_V1.ai_connectors.opus46_connector import Opus46Connector
from app.modules.ChapterStudio_V1.ai_connectors.qwen27b_modal_connector import Qwen27BModalConnector
from app.modules.ChapterStudio_V1.ai_connectors.tts_v1_connector import TTSV1Connector
from app.modules.ChapterStudio_V1.common.config import (
    active_planner_model,
    active_text_model,
    active_tts_model,
    active_verifier_model,
    text_fallback_after_failures,
    text_primary_attempt_timeout_sec,
)

_LOG = logging.getLogger(__name__)

# Gemini CLI는 테스트 전용 커넥터다 — 프로덕션 레지스트리에서 선택되려면
# 반드시 GEMINI_CLI_ENABLED=true 환경변수가 설정되어야 한다.
_GEMINI_CONNECTORS: frozenset[str] = frozenset({"gemini_cli"})

Connector = AIConnector | TTSConnector


class ConnectorFactory(Protocol):
    def __call__(self) -> Connector:
        """테스트에서 mock class를 같은 형태로 주입하기 위함이다."""
        ...


@runtime_checkable
class AsyncCloseable(Protocol):
    async def aclose(self) -> None:
        """비동기 네트워크 리소스를 닫는다."""
        ...


_REGISTRY: dict[str, ConnectorFactory] = {
    "qwen27b_modal": Qwen27BModalConnector,
    "opus46": Opus46Connector,
    "tts_v1": TTSV1Connector,
    "codex_cli": CodexCLIConnector,
    "claude_sonnet": ClaudeSonnetConnector,
    "gemini_cli": GeminiCLIConnector,
    "tts_v2": lambda: _build_tts_v2_connector(),
    # 로컬 개발 전용 — MLX Qwen3.6-35B-A3B 텍스트 생성 (AI API 비용 절약)
    # 프로덕션에서는 ACTIVE_TEXT_MODEL=claude_sonnet 으로 교체한다
    "mlx_qwen3_local": lambda: _build_mlx_qwen3_connector(),
}
_CACHE: dict[str, Connector] = {}
_POLISH_CACHE: Kanana2Connector | None = None


def _build_failover_connector() -> FailoverAIConnector:
    """Qwen27B → Claude Sonnet 폴백 래퍼를 생성한다."""
    return FailoverAIConnector(
        primary_factory=Qwen27BModalConnector,
        fallback_factory=ClaudeSonnetConnector,
        name="qwen27b_sonnet_fallback",
        failure_threshold=text_fallback_after_failures(),
        primary_timeout_sec=text_primary_attempt_timeout_sec(),
    )


def _build_tts_v2_connector() -> TTSConnector:
    """무거운 TTS_V2 의존성은 실제 선택 시점에만 로드한다."""
    from app.modules.ChapterStudio_V1.ai_connectors.tts_v2_connector import TTSV2Connector

    return TTSV2Connector()


def _build_mlx_qwen3_connector() -> AIConnector:
    """MLX Qwen3 커넥터는 mlx-lm이 설치된 경우에만 임포트한다."""
    from app.modules.ChapterStudio_V1.ai_connectors.mlx_qwen3_local_connector import (
        MlxQwen3LocalConnector,
    )
    return MlxQwen3LocalConnector()


def _build_gemini_genai_connector() -> AIConnector:
    """google-genai SDK 커넥터는 선택 시점에만 로드한다."""
    from app.modules.ChapterStudio_V1.ai_connectors.gemini_genai_connector import (
        GeminiGenAIConnector,
    )
    return GeminiGenAIConnector()


# 폴백 래퍼는 팩토리 함수를 등록한다
_REGISTRY["qwen27b_sonnet_fallback"] = _build_failover_connector
_REGISTRY["gemini_flash"] = _build_gemini_genai_connector


def get_connector(name: str) -> Connector:
    """커넥터 인스턴스를 한 번만 생성해 노드 호출 비용을 줄인다.

    Gemini CLI 커넥터는 테스트 전용이다. GEMINI_CLI_ENABLED=true 환경변수 없이
    선택하면 ModelNotFoundError를 발생시켜 프로덕션 선택을 차단한다.
    """
    if name in _CACHE:
        return _CACHE[name]
    # Gemini 선택 시 명시적 활성화 플래그를 요구한다
    if name in _GEMINI_CONNECTORS:
        enabled = os.getenv("GEMINI_CLI_ENABLED", "").strip().lower() == "true"
        if not enabled:
            raise ModelNotFoundError(
                f"'{name}' 커넥터는 테스트 전용입니다. "
                "프로덕션에서 Gemini를 사용하려면 GEMINI_CLI_ENABLED=true 를 명시 설정하세요. "
                "프로덕션 기본 커넥터는 claude_sonnet 입니다."
            )
        _LOG.warning(
            "⚠️  Gemini CLI 커넥터(%s)가 선택되었습니다. "
            "이 커넥터는 테스트 전용입니다 — 프로덕션 환경에서 사용을 권장하지 않습니다.",
            name,
        )
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ModelNotFoundError(f"{name} 커넥터가 등록되지 않았다.")
    instance = cls()
    _CACHE[name] = instance
    return instance


def get_text_connector() -> AIConnector:
    """환경 설정의 활성 텍스트 모델을 Protocol로 검증해 반환한다."""
    return _as_ai_connector(get_connector(active_text_model()))


def get_planner_connector() -> AIConnector:
    """Planner는 Opus 계열 커넥터만 AIConnector로 노출한다."""
    return _as_ai_connector(get_connector(active_planner_model()))


def get_verifier_connector() -> AIConnector:
    """내용 정확성 검증용 커넥터를 반환한다.

    ACTIVE_VERIFIER_MODEL이 설정돼 있으면 그 커넥터를, 없으면 활성 텍스트 커넥터를
    그대로 쓴다(별도 검증 모델을 강제하지 않는다).
    """
    name = active_verifier_model()
    if name is None:
        return get_text_connector()
    return _as_ai_connector(get_connector(name))


def get_tts_connector() -> TTSConnector:
    """TTS 합성 커넥터는 텍스트 생성 커넥터와 분리해 반환한다."""
    connector = get_connector(active_tts_model())
    if not isinstance(connector, TTSConnector):
        raise ModelNotFoundError("활성 TTS 커넥터가 TTSConnector가 아니다.")
    return connector


def get_polish_connector() -> Kanana2Connector:
    """Kanana2 교정 커넥터는 생성/검증 모델 레지스트리와 분리해 반환한다."""
    global _POLISH_CACHE
    if _POLISH_CACHE is None:
        _POLISH_CACHE = Kanana2Connector()
    return _POLISH_CACHE


def clear_cache() -> None:
    """테스트 격리를 위해 싱글톤 캐시를 비운다."""
    global _POLISH_CACHE
    _CACHE.clear()
    _POLISH_CACHE = None


async def close_all() -> None:
    """lifespan 종료 시 캐시된 커넥터 리소스를 닫고 캐시를 비운다."""
    for connector in list(_CACHE.values()):
        if isinstance(connector, AsyncCloseable):
            await connector.aclose()
    clear_cache()


def _as_ai_connector(connector: Connector) -> AIConnector:
    if not isinstance(connector, AIConnector):
        raise ModelNotFoundError("활성 커넥터가 AIConnector가 아니다.")
    return connector


__all__ = [
    "_CACHE",
    "_REGISTRY",
    "clear_cache",
    "close_all",
    "get_connector",
    "get_planner_connector",
    "get_polish_connector",
    "get_text_connector",
    "get_tts_connector",
    "get_verifier_connector",
]
