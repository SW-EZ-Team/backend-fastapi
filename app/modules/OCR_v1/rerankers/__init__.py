"""리랭커 패키지 — Reranker 구현체를 한 곳에서 re-export한다.

현재 기본 리랭커는 BGE-Reranker-v2-m3(Cross-Encoder 방식)이다.
"""
from __future__ import annotations

from .bge_reranker import BGEReranker

__all__ = ["BGEReranker"]
