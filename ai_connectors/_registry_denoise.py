"""노이즈 제거(Denoise) 커넥터 서브레지스트리.

DENOISE_CONNECTORS dict 와 get_denoise_connector 팩토리를 담는다.
외부 코드는 이 파일을 직접 import 하지 않고 ai_connectors.registry 를 사용한다.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

from .base import DenoiseConnector
from .denoise.clearvoice_mossformer2_connector import ClearVoiceMossFormer2Connector
from .denoise.mossformer2_modal_connector import MossFormer2ModalConnector
from .errors import ModelNotFoundError

_LOG = logging.getLogger(__name__)

# Denoise 커넥터 팩토리 맵 (DenoiseConnector 구현체)
DENOISE_CONNECTORS: dict[str, Callable[[], DenoiseConnector]] = {
    "mossformer2-se-48k": lambda: ClearVoiceMossFormer2Connector(),
    "mossformer2-modal": lambda: MossFormer2ModalConnector(),
}


def get_denoise_connector(model_name: str | None = None) -> DenoiseConnector:
    """.env 의 AI_MODEL_DENOISE 또는 명시된 model_name 으로 Denoise 커넥터 반환."""
    name = model_name or os.getenv("AI_MODEL_DENOISE", "mossformer2-se-48k")
    if name not in DENOISE_CONNECTORS:
        raise ModelNotFoundError(
            f"Unknown denoise model: {name}. "
            f"Registered: {list(DENOISE_CONNECTORS.keys())}"
        )
    return DENOISE_CONNECTORS[name]()
