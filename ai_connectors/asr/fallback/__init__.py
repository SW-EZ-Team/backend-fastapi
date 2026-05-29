"""LangGraph 기반 2단 폴백 ASR 모듈.

사용 예:
    from ai_connectors.asr.fallback import FallbackASRConnector
    from ai_connectors.asr.fallback.config import resolve_tier_models
"""
from .connector import FallbackASRConnector

__all__ = ["FallbackASRConnector"]
