from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import cast

from app.modules.ChapterStudio_V1.app.reference_books.retrieval import build_reference_book_context
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext, ReferenceBookPage


def reference_pages_from_ocr_result(
    result: Mapping[str, object],
    *,
    source_title: str = "",
) -> list[ReferenceBookPage]:
    """OCRPipelineResult 계열 dict를 페이지 단위 참고도서 텍스트로 정규화한다."""
    pages = _pages_from_sequence(result.get("pages"), source_title=source_title)
    if pages:
        return pages
    return _pages_from_sequence(result.get("page_results"), source_title=source_title)


def reference_context_from_ocr_result(
    result: Mapping[str, object],
    queries: Sequence[str],
    *,
    source_title: str = "",
    max_hits: int = 5,
) -> ReferenceBookContext:
    """OCR 결과 dict에서 바로 강의 생성용 참고도서 컨텍스트를 만든다."""
    title = source_title or _text(result, "source_title") or _text(result, "pdf")
    pages = reference_pages_from_ocr_result(result, source_title=title)
    return build_reference_book_context(
        pages,
        queries,
        source_title=title,
        ocr_model=_text(result, "ocr_model"),
        max_hits=max_hits,
    )


def reference_pages_from_jsonl_lines(
    lines: Iterable[str],
    *,
    source_title: str = "",
) -> list[ReferenceBookPage]:
    """벤치마크 JSONL(page/text) 산출물을 참고도서 페이지 목록으로 바꾼다."""
    pages: list[ReferenceBookPage] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            mapped = cast(Mapping[str, object], payload)
            page = _page_number(mapped)
            text = _text(mapped, "text")
            if page is not None and text:
                pages.append(
                    ReferenceBookPage(
                        page=page,
                        text=text,
                        source_title=source_title,
                    )
                )
    return pages


def _pages_from_sequence(value: object, *, source_title: str) -> list[ReferenceBookPage]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []

    pages: list[ReferenceBookPage] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        mapped = cast(Mapping[str, object], item)
        page = _page_number(mapped)
        text = _text(mapped, "text") or _text(mapped, "text_preview")
        if page is None or not text:
            continue
        pages.append(ReferenceBookPage(page=page, text=text, source_title=source_title))
    return pages


def _page_number(source: Mapping[str, object]) -> int | None:
    for key in ("page_num", "page"):
        value = source.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    return None


def _text(source: Mapping[str, object], key: str) -> str:
    value = source.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""
