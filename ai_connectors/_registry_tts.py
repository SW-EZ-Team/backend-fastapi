"""TTS(텍스트-음성 변환) 커넥터 서브레지스트리.

TTS_CONNECTORS dict, 환경변수 파싱 헬퍼, get_tts_connector 팩토리를 담는다.
활성 경로는 Gemini TTS 이며, 배포용 Modal(qwen3-tts-modal) 커넥터는 보존한다.
외부 코드는 이 파일을 직접 import 하지 않고 ai_connectors.registry 를 사용한다.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

from .base import TTSConnector
from .errors import ModelNotFoundError
from .tts.gemini_tts_connector import GeminiTTSConnector
from .tts.qwen3_tts_modal_connector import Qwen3TTSModalConnector

_LOG = logging.getLogger(__name__)

# TTS 커넥터 팩토리 맵 (TTSConnector 구현체)
# 활성 기본은 gemini-tts. qwen3-tts-modal 은 배포 시에만 .env 로 선택한다.
TTS_CONNECTORS: dict[str, Callable[[], TTSConnector]] = {
    "gemini-tts": lambda: GeminiTTSConnector(),
    "qwen3-tts-modal": lambda: Qwen3TTSModalConnector(),
}


def _wrap_with_openai_failover(connector: TTSConnector) -> TTSConnector:
    """선택된 커넥터가 Gemini TTS 이고 OpenAI 폴백이 활성이면 폴백 래퍼로 감싼다.

    활성 조건: 커넥터가 gemini-tts + OPENAI_API_KEY 존재 + OPENAI_FALLBACK_ENABLED!=false.
    OpenAI SDK·키 미설치 환경에서도 ImportError 를 흡수해 원본을 돌려준다.
    """
    from common.text_config import openai_api_key, openai_fallback_enabled

    if getattr(connector, "name", "") != "gemini-tts":
        return connector
    if not openai_fallback_enabled() or openai_api_key() is None:
        return connector
    try:
        from ._failover import FailoverTTSConnector
        from .tts.openai_tts_connector import OpenAITTSConnector
    except ImportError as exc:
        _LOG.warning(
            "OpenAI TTS 폴백 래핑 건너뜀 (ImportError: %s). `uv add openai` 실행 필요",
            exc,
        )
        return connector
    return FailoverTTSConnector(connector, lambda: OpenAITTSConnector())


def get_tts_connector(model_name: str | None = None) -> TTSConnector:
    """.env 의 AI_MODEL_TTS 또는 명시된 model_name 으로 TTS 커넥터 반환."""
    name = model_name or os.getenv("AI_MODEL_TTS", "gemini-tts")
    if name not in TTS_CONNECTORS:
        raise ModelNotFoundError(
            f"Unknown TTS model: {name}. Registered: {list(TTS_CONNECTORS.keys())}"
        )
    return _wrap_with_openai_failover(TTS_CONNECTORS[name]())
