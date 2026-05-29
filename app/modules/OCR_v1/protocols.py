"""OCR_v1 컴포넌트 교체 인터페이스 — Protocol 기반 스왑 계약.

각 Protocol 을 구현한 구체 클래스를 registry.py 에서 등록하고,
호출자는 이 Protocol 타입만 참조하므로 구현체를 자유롭게 교체할 수 있다.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class OCREngine(Protocol):
    """OCR 엔진 프로토콜 — Marker, MinerU 등 교체 단위.

    엔진이 바뀌어도 호출자 코드를 수정할 필요가 없도록 계약을 고정한다.
    """

    name: str  # 레지스트리 등록 키와 동일한 엔진 식별자

    async def extract(
        self,
        pdf_bytes: bytes,
        pages: list[int] | None = None,
        force_ocr: bool = False,
        use_llm: bool = False,
    ) -> list[dict]: ...
    """PDF 에서 페이지별 마크다운·표·수식을 추출한다.

    pages 가 None 이면 전체 페이지를 처리한다.
    force_ocr=True 면 텍스트 레이어가 있어도 이미지 OCR 을 강제한다.
    use_llm=True 면 엔진 내장 LLM 교정을 활성화한다 (지원 엔진만).
    반환: [{"page_num": int, "markdown": str, "tables": [...], "formulas": [...]}]
    """

    def supports(self, feature: str) -> bool: ...
    """엔진이 특정 기능을 지원하는지 확인한다 (예: "llm_correction", "table")."""


@runtime_checkable
class Chunker(Protocol):
    """청킹 프로토콜 — 섹션/페이지/토큰 기반 전략 교체 단위."""

    async def chunk(
        self,
        markdown: str,
        pages: list[dict],
    ) -> list[dict]: ...
    """마크다운을 청크 목록으로 분할한다.

    pages 는 PageExtraction 형식의 딕셔너리 목록이다.
    반환: ChunkRecord 형식의 딕셔너리 목록
    """


@runtime_checkable
class Embedder(Protocol):
    """임베딩 프로토콜 — dense+sparse 벡터 생성 단위.

    BGE-M3 처럼 단일 모델이 dense/sparse 를 동시에 생성하는 경우를 기본으로 상정한다.
    """

    name: str  # 레지스트리 등록 키

    async def embed(self, texts: list[str]) -> list[dict]: ...
    """텍스트 목록을 벡터 딕셔너리 목록으로 변환한다.

    반환 딕셔너리 형식:
    {
        "dense": list[float],
        "sparse": {"indices": list[int], "values": list[float]},
    }
    """


@runtime_checkable
class VectorStore(Protocol):
    """벡터DB 프로토콜 — 저장+검색 추상화.

    Qdrant 기본 구현체를 다른 DB 로 교체할 때 이 계약만 지키면 된다.
    """

    async def upsert(
        self,
        collection: str,
        points: list[dict],
    ) -> int: ...
    """포인트를 컬렉션에 업서트하고 저장된 포인트 수를 반환한다."""

    async def search(
        self,
        collection: str,
        query_embedding: dict,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[dict]: ...
    """하이브리드 검색을 수행하고 관련도 순 결과를 반환한다."""

    async def ensure_collection(self, collection: str) -> None: ...
    """컬렉션이 없으면 생성한다 (이미 있으면 아무 것도 하지 않는다)."""


@runtime_checkable
class Reranker(Protocol):
    """리랭커 프로토콜 — cross-encoder 기반 재정렬 단위.

    벡터 검색 결과를 의미 기반으로 재정렬해 정밀도를 높인다.
    """

    name: str  # 레지스트리 등록 키

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 5,
    ) -> list[dict]: ...
    """query 와 documents 를 크로스인코더로 재정렬한다.

    반환 딕셔너리 형식:
    {"index": int, "score": float, "text": str}
    """
