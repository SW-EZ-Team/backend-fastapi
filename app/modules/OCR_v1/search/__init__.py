"""검색 패키지 — 하이브리드 검색과 인용 빌더를 re-export한다.

hybrid_search: Dense+Sparse 벡터 검색 후 BGE-Reranker로 재정렬
build_citations: 검색 결과를 구조화된 인용 형식으로 변환
"""
from __future__ import annotations

from .citation_builder import build_citations
from .hybrid_retriever import hybrid_search

__all__ = ["hybrid_search", "build_citations"]
