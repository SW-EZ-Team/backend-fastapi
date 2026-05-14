from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector, TTSConnector
from app.modules.ChapterStudio_V1.ai_connectors.codex_cli_connector import CodexCLIConnector
from app.modules.ChapterStudio_V1.ai_connectors.errors import ModelNotFoundError
from app.modules.ChapterStudio_V1.ai_connectors.opus46_connector import Opus46Connector
from app.modules.ChapterStudio_V1.ai_connectors.qwen27b_modal_connector import Qwen27BModalConnector
from app.modules.ChapterStudio_V1.ai_connectors.tts_v1_connector import TTSV1Connector
from app.modules.ChapterStudio_V1.common.config import active_planner_model, active_text_model, active_tts_model

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
}
_CACHE: dict[str, Connector] = {}


def get_connector(name: str) -> Connector:
    """커넥터 인스턴스를 한 번만 생성해 노드 호출 비용을 줄인다."""
    if name in _CACHE:
        return _CACHE[name]
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


def get_tts_connector() -> TTSConnector:
    """TTS 합성 커넥터는 텍스트 생성 커넥터와 분리해 반환한다."""
    connector = get_connector(active_tts_model())
    if not isinstance(connector, TTSConnector):
        raise ModelNotFoundError("활성 TTS 커넥터가 TTSConnector가 아니다.")
    return connector


def clear_cache() -> None:
    """테스트 격리를 위해 싱글톤 캐시를 비운다."""
    _CACHE.clear()


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
    "get_text_connector",
    "get_tts_connector",
]
