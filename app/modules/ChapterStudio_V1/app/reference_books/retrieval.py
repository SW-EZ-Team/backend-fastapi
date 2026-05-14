from __future__ import annotations

import re
from collections.abc import Sequence

from app.modules.ChapterStudio_V1.app.reference_books.schemas import (
    ReferenceBookContext,
    ReferenceBookHit,
    ReferenceBookPage,
)

_TERM_RE = re.compile(r"[0-9A-Za-z가-힣]+")
_SPACE_RE = re.compile(r"\s+")
_STOPWORDS = frozenset(
    {
        "그리고",
        "그러나",
        "대한",
        "위한",
        "학습",
        "이해",
        "핵심",
        "개념",
        "내용",
        "강의",
        "챕터",
        "정리",
        "목표",
        "취약점",
        "문제",
        "설명",
        "예시",
        "실습",
    }
)


def build_reference_book_context(
    pages: Sequence[ReferenceBookPage],
    queries: Sequence[str],
    *,
    source_title: str = "",
    ocr_model: str = "",
    max_hits: int = 5,
    snippet_chars: int = 360,
) -> ReferenceBookContext:
    """페이지 단위 OCR 텍스트에서 강의 주제와 가까운 발췌를 고른다."""
    query = compact_text(" ".join(item for item in queries if item.strip()))
    terms = query_terms(query)
    if not pages or not terms:
        return ReferenceBookContext(
            source_title=source_title,
            query=query,
            page_count=len(pages),
            ocr_model=ocr_model,
        )

    scored: list[ReferenceBookHit] = []
    for page in pages:
        text = compact_text(page.text)
        if len(text) < 20:
            continue
        score, matched = _score_page(text, terms)
        if score <= 0:
            continue
        scored.append(
            ReferenceBookHit(
                page=page.page,
                snippet=_best_snippet(text, matched, snippet_chars),
                score=score,
                source_title=page.source_title or source_title,
                matched_terms=matched[:8],
            )
        )

    hits = sorted(scored, key=lambda item: (-item.score, item.page))[:max(1, max_hits)]
    return ReferenceBookContext(
        source_title=source_title,
        query=query,
        page_count=len(pages),
        ocr_model=ocr_model,
        hits=hits,
    )


def compact_text(value: str) -> str:
    """OCR 줄바꿈과 과도한 공백을 LLM 입력용 한 줄 텍스트로 줄인다."""
    return _SPACE_RE.sub(" ", value).strip()


def query_terms(value: str) -> list[str]:
    """검색 쿼리에서 너무 일반적인 단어를 제거한 용어 목록을 만든다."""
    terms = _query_terms(value, skip_stopwords=True)
    if terms:
        return terms
    return _query_terms(value, skip_stopwords=False)


def _query_terms(value: str, *, skip_stopwords: bool) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in _TERM_RE.findall(value):
        term = raw.strip()
        lowered = term.lower()
        if len(term) < 2 or lowered in seen:
            continue
        if skip_stopwords and term in _STOPWORDS:
            continue
        seen.add(lowered)
        terms.append(term)
    return terms


def _score_page(text: str, terms: Sequence[str]) -> tuple[float, list[str]]:
    score = 0.0
    matched: list[str] = []
    lowered = text.lower()
    for term in terms:
        count = lowered.count(term.lower())
        if count == 0:
            continue
        matched.append(term)
        weight = 2.0 if len(term) >= 4 else 1.0
        score += min(count, 4) * weight
    if len(matched) >= 2:
        score += len(matched) * 0.75
    return score, matched


def _best_snippet(text: str, terms: Sequence[str], snippet_chars: int) -> str:
    if not terms:
        return _trim_snippet(text[:snippet_chars])

    lowered = text.lower()
    positions = [lowered.find(term.lower()) for term in terms if lowered.find(term.lower()) >= 0]
    center = min(positions) if positions else 0
    half = max(80, snippet_chars // 2)
    start = max(0, center - half)
    end = min(len(text), start + snippet_chars)
    return _trim_snippet(text[start:end], prefix=start > 0, suffix=end < len(text))


def _trim_snippet(value: str, *, prefix: bool = False, suffix: bool = False) -> str:
    snippet = value.strip(" ,.;:\n\t")
    if prefix:
        snippet = f"... {snippet}"
    if suffix:
        snippet = f"{snippet} ..."
    return snippet
