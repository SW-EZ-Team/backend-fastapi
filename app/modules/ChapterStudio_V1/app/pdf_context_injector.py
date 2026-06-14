"""PDF 소스 강의의 참고도서 컨텍스트 자동 주입 — 원자 모듈.

source_mode=pdf이고 reference_book_context가 비어 있는 GenerationContext에
Qdrant RAG 검색 결과를 주입해 반환한다. 실패 시 원본 context를 그대로 반환한다.

한 가지 책임만 가진다: PDF → Qdrant 검색 → ReferenceBookContext 주입.
"""
from __future__ import annotations

import logging
import os
import urllib.parse

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.app.reference_books.retrieval import build_reference_book_context
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookPage

_LOG = logging.getLogger(__name__)


def collection_name_from_source_ref(source_ref: str) -> str:
    """source_ref(S3 URL 또는 bare 파일명)에서 OCR 인제스트와 동일한 Qdrant 컬렉션명을 만든다.

    커리큘럼 생성(curriculum_generate)에서도 같은 유도식을 재사용하는 단일 진실 소스다.

    OCR 인제스트(connector.py:37)는 bare 파일명에 대해
    `filename.rsplit(".", 1)[0].replace(" ", "_")` 를 적용한다.
    source_ref 가 S3 URL 이면 먼저 URL 디코딩 → basename 추출 후 동일 변환을 적용해
    두 유도식이 같은 문자열을 내도록 보장한다.
    """
    # URL 이면 퍼센트 인코딩 해제 후 경로에서 파일명만 추출한다
    parsed = urllib.parse.urlparse(source_ref)
    if parsed.scheme in ("http", "https", "s3"):
        bare_name = os.path.basename(urllib.parse.unquote(parsed.path))
    else:
        # bare 파일명 또는 상대경로 그대로 사용
        bare_name = os.path.basename(source_ref) or source_ref
    # OCR 인제스트와 완전히 동일한 정규화: 확장자 제거 + 공백 → 언더스코어
    return bare_name.rsplit(".", 1)[0].replace(" ", "_")


async def inject_reference_context_if_pdf(context: GenerationContext) -> GenerationContext:
    """source_mode=pdf이고 reference_book_context가 비어 있으면 Qdrant RAG로 채운다.

    OCR 인제스트 시 Qdrant에 저장된 청크를 강의 주제+챕터명으로 검색해 자동 주입한다.
    실패하면 원본 context를 그대로 반환해 강의 생성 플로우가 중단되지 않게 한다.
    """
    if context.source_mode != "pdf" or context.reference_book_context is not None:
        return context
    if not context.pdf_file_name:
        return context

    collection = collection_name_from_source_ref(context.pdf_file_name)
    query = f"{context.topic} {context.chapter_title} {context.chapter_brief}".strip()
    try:
        from app.modules.OCR_v1.search import hybrid_search

        hits = await hybrid_search(query, collection, top_k=20)
        if not hits:
            # 0 hit 는 컬렉션명 불일치 또는 OCR 미완료 가능성이 있으므로 warning 으로 기록한다
            _LOG.warning(
                "[pdf-injector] PDF 참고서 컨텍스트 0 hit — lesson_id=%s, collection=%s",
                context.lesson_id,
                collection,
            )
            return context

        pages = [
            ReferenceBookPage(
                page=int(h.get("payload", {}).get("page_num", 1) or 1),
                text=str(h.get("text", "")),
                source_title=context.pdf_file_name,
            )
            for h in hits
            if h.get("text")
        ]
        ref_ctx = build_reference_book_context(
            pages,
            [query],
            source_title=context.pdf_file_name,
            max_hits=20,
        )
        if not ref_ctx.has_hits():
            return context

        _LOG.info(
            "[pdf-injector] 참고도서 컨텍스트 주입 완료 — lesson_id=%s, hits=%d",
            context.lesson_id,
            len(ref_ctx.hits),
        )
        return context.model_copy(update={"reference_book_context": ref_ctx})
    except Exception as exc:
        # Qdrant 미연결·컬렉션 없음 등 인프라 예외는 강의 생성 실패로 번지지 않게 경고만 남긴다
        _LOG.warning(
            "[pdf-injector] PDF 참고도서 주입 실패(무시) — lesson_id=%s, error=%s",
            context.lesson_id,
            exc,
        )
        return context
