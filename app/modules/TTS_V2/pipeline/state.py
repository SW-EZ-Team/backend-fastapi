"""TTS V2 — 파이프라인 상태 재수출 모듈.

schemas.state 의 타입을 pipeline 패키지 경계에서 재수출해
내부 노드들이 schemas 경로를 직접 참조하지 않아도 되도록 한다.
"""
from __future__ import annotations

from app.modules.TTS_V2.schemas.state import AudiobookState, ChunkRecord

__all__ = ["AudiobookState", "ChunkRecord"]
