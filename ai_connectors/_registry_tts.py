"""TTS(텍스트-음성 변환) 커넥터 서브레지스트리.

TTS_CONNECTORS dict, 환경변수 파싱 헬퍼, get_tts_connector 팩토리를 담는다.
활성 경로는 Gemini TTS 이며, 배포용 Modal(qwen3-tts-modal) 커넥터는 보존한다.
외부 코드는 이 파일을 직접 import 하지 않고 ai_connectors.registry 를 사용한다.
"""
from __future__ import annotations

import os
from typing import Callable

from .base import TTSConnector
from .errors import ModelNotFoundError
from .tts.gemini_tts_connector import GeminiTTSConnector
from .tts.qwen3_tts_modal_connector import Qwen3TTSModalConnector

# TTS 커넥터 팩토리 맵 (TTSConnector 구현체)
# 활성 기본은 gemini-tts. qwen3-tts-modal 은 배포 시에만 .env 로 선택한다.
TTS_CONNECTORS: dict[str, Callable[[], TTSConnector]] = {
    "gemini-tts": lambda: GeminiTTSConnector(),
    "qwen3-tts-modal": lambda: Qwen3TTSModalConnector(),
}


def get_tts_connector(model_name: str | None = None) -> TTSConnector:
    """.env 의 AI_MODEL_TTS 또는 명시된 model_name 으로 TTS 커넥터 반환."""
    name = model_name or os.getenv("AI_MODEL_TTS", "gemini-tts")
    if name not in TTS_CONNECTORS:
        raise ModelNotFoundError(
            f"Unknown TTS model: {name}. Registered: {list(TTS_CONNECTORS.keys())}"
        )
    return TTS_CONNECTORS[name]()
