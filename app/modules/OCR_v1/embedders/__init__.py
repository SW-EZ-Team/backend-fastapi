"""임베더 패키지 — Embedder 구현체를 한 곳에서 re-export한다.

현재 기본 임베더는 BGE-M3(Dense + Sparse 하이브리드)이다.
"""
from __future__ import annotations

from .bge_m3_embedder import BGEM3Embedder

__all__ = ["BGEM3Embedder"]
