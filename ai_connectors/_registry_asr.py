"""ASR(자동 음성 인식) 커넥터 서브레지스트리.

ASR_CONNECTORS dict 와 get_asr_connector 팩토리를 담는다.
외부 코드는 이 파일을 직접 import 하지 않고 ai_connectors.registry 를 사용한다.
"""
from __future__ import annotations

import logging
from typing import Callable

from .asr.gemini_asr_connector import GeminiASRConnector
from .asr.qwen3_asr_modal_connector import Qwen3ASRModalConnector
from .base import ASRConnector
from .errors import ModelNotFoundError

import os

_LOG = logging.getLogger(__name__)

# ASR 커넥터 팩토리 맵 (ASRConnector 구현체)
# 활성 기본은 gemini-asr. qwen3-asr-modal 은 배포 시에만 .env 로 선택한다.
ASR_CONNECTORS: dict[str, Callable[[], ASRConnector]] = {
    "gemini-asr": lambda: GeminiASRConnector(),
    "qwen3-asr-modal": lambda: Qwen3ASRModalConnector(),
}

# FallbackASRConnector — Gemini → Qwen3 ASR Modal 폴백.
# LangGraph 의존성 미설치 환경에서도 개별 ASR 커넥터는 정상 동작하도록 보호한다.
try:
    from .asr.fallback import FallbackASRConnector
    from .asr.fallback.config import resolve_tier_models

    def _make_fallback_asr() -> FallbackASRConnector:
        """.env 의 ASR_FALLBACK_TIERS 를 해석한 뒤 팩토리를 주입해 생성한다.

        각 tier 커넥터는 호출 시점에 지연 로드된다 (ASR_CONNECTORS[name]()).
        순환 import 방지를 위해 팩토리 클로저 안에서 ASR_CONNECTORS 를 참조한다.
        """
        tier_names = list(resolve_tier_models())
        # 실제 등록된 커넥터만 tier 에 포함 (미설치 환경 대응)
        valid = [n for n in tier_names if n in ASR_CONNECTORS]
        if not valid:
            raise ModelNotFoundError(
                f"asr-fallback 의 tier 후보 중 등록된 커넥터 없음. "
                f"요청: {tier_names}, 등록: {list(ASR_CONNECTORS.keys())}"
            )
        factories = [ASR_CONNECTORS[n] for n in valid]
        return FallbackASRConnector(
            tier_factories=factories,
            tier_model_names=valid,
        )

    ASR_CONNECTORS["asr-fallback"] = _make_fallback_asr
except ImportError as _fallback_import_err:
    _LOG.warning(
        "asr-fallback 커넥터 등록 건너뜀 (ImportError: %s). "
        "`uv pip install langgraph` 실행 필요",
        _fallback_import_err,
    )


def get_asr_connector(model_name: str | None = None) -> ASRConnector:
    """.env 의 AI_MODEL_ASR 또는 명시된 model_name 으로 ASR 커넥터 반환."""
    name = model_name or os.getenv("AI_MODEL_ASR", "gemini-asr")
    if name not in ASR_CONNECTORS:
        raise ModelNotFoundError(
            f"Unknown ASR model: {name}. Registered: {list(ASR_CONNECTORS.keys())}"
        )
    return ASR_CONNECTORS[name]()
