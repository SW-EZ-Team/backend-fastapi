"""OCR_v1 컴포넌트 레지스트리 — 구현체를 이름으로 지연 등록한다.

ImportError 는 경고로 처리해 선택적 의존성이 없어도 서버가 기동되도록 한다.
실제 인스턴스가 필요할 때만 팩토리를 호출(지연 로드)해 메모리 낭비를 방지한다.
"""
from __future__ import annotations

import logging
from typing import Callable

from . import config as cfg

_LOG = logging.getLogger(__name__)

# 레지스트리 딕셔너리 — {이름: 팩토리 함수}
ENGINE_REGISTRY: dict[str, Callable] = {}
EMBEDDER_REGISTRY: dict[str, Callable] = {}
STORE_REGISTRY: dict[str, Callable] = {}
RERANKER_REGISTRY: dict[str, Callable] = {}
CHUNKER_REGISTRY: dict[str, Callable] = {}

# --- Marker 엔진 등록 ---
try:
    from .engines.marker_engine import MarkerEngine
    ENGINE_REGISTRY["marker"] = lambda: MarkerEngine()
except ImportError as e:
    _LOG.warning("Marker 엔진 등록 건너뜀 (marker 패키지 미설치): %s", e)

# --- MinerU 엔진 등록 ---
try:
    from .engines.mineru_engine import MinerUEngine
    ENGINE_REGISTRY["mineru"] = lambda: MinerUEngine()
except ImportError as e:
    _LOG.warning("MinerU 엔진 등록 건너뜀 (mineru 패키지 미설치): %s", e)

# --- BGE-M3 임베더 등록 ---
try:
    from .embedders.bge_m3_embedder import BGEM3Embedder
    EMBEDDER_REGISTRY["bge-m3"] = lambda: BGEM3Embedder()
except ImportError as e:
    _LOG.warning("BGE-M3 임베더 등록 건너뜀 (FlagEmbedding 미설치): %s", e)

# --- Qdrant 스토어 등록 ---
try:
    from .stores.qdrant_store import QdrantStore
    STORE_REGISTRY["qdrant"] = lambda: QdrantStore()
except ImportError as e:
    _LOG.warning("Qdrant 스토어 등록 건너뜀 (qdrant-client 미설치): %s", e)

# --- BGE 리랭커 등록 ---
try:
    from .rerankers.bge_reranker import BGEReranker
    RERANKER_REGISTRY["bge-reranker"] = lambda: BGEReranker()
except ImportError as e:
    _LOG.warning("BGE 리랭커 등록 건너뜀 (FlagEmbedding 미설치): %s", e)

# --- 섹션 청커 등록 ---
try:
    from .chunking.section_chunker import SectionChunker
    CHUNKER_REGISTRY["section"] = lambda: SectionChunker()
except ImportError as e:
    _LOG.warning("섹션 청커 등록 건너뜀 (tiktoken 미설치): %s", e)


def get_engine(name: str | None = None):
    """OCR 엔진 인스턴스를 반환한다. name 미지정 시 config 기본값 사용."""
    key = name or cfg.primary_engine()
    if key not in ENGINE_REGISTRY:
        raise KeyError(f"OCR 엔진 '{key}' 미등록. 가용: {list(ENGINE_REGISTRY)}")
    return ENGINE_REGISTRY[key]()


def get_fallback_engine():
    """폴백 엔진 인스턴스를 반환한다."""
    return get_engine(cfg.fallback_engine())


def get_embedder(name: str | None = None):
    """임베더 인스턴스를 반환한다. name 미지정 시 bge-m3 사용."""
    key = name or "bge-m3"
    if key not in EMBEDDER_REGISTRY:
        raise KeyError(f"임베더 '{key}' 미등록. 가용: {list(EMBEDDER_REGISTRY)}")
    return EMBEDDER_REGISTRY[key]()


def get_store(name: str | None = None):
    """벡터스토어 인스턴스를 반환한다. name 미지정 시 qdrant 사용."""
    key = name or "qdrant"
    if key not in STORE_REGISTRY:
        raise KeyError(f"스토어 '{key}' 미등록. 가용: {list(STORE_REGISTRY)}")
    return STORE_REGISTRY[key]()


def get_reranker(name: str | None = None):
    """리랭커 인스턴스를 반환한다. name 미지정 시 bge-reranker 사용."""
    key = name or "bge-reranker"
    if key not in RERANKER_REGISTRY:
        raise KeyError(f"리랭커 '{key}' 미등록. 가용: {list(RERANKER_REGISTRY)}")
    return RERANKER_REGISTRY[key]()


def get_chunker(name: str | None = None):
    """청커 인스턴스를 반환한다. name 미지정 시 section 사용."""
    key = name or "section"
    if key not in CHUNKER_REGISTRY:
        raise KeyError(f"청커 '{key}' 미등록. 가용: {list(CHUNKER_REGISTRY)}")
    return CHUNKER_REGISTRY[key]()
