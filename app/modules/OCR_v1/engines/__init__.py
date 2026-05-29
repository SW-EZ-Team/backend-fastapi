"""엔진 패키지 — OCREngine 구현체를 한 곳에서 re-export한다.

MarkerEngine(고품질 Born-Digital/스캔)과 MinerUEngine(CJK 강화 폴백)을
외부에서 동일한 경로로 import할 수 있도록 노출한다.
"""
from __future__ import annotations

from .marker_engine import MarkerEngine
from .mineru_engine import MinerUEngine

__all__ = ["MarkerEngine", "MinerUEngine"]
