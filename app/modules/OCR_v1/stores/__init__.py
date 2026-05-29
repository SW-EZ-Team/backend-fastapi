"""벡터 저장소 패키지 — VectorStore 구현체를 한 곳에서 re-export한다.

현재 기본 저장소는 Qdrant(온디맨드 컬렉션 + 하이브리드 검색)이다.
"""
from __future__ import annotations

from .qdrant_store import QdrantStore

__all__ = ["QdrantStore"]
