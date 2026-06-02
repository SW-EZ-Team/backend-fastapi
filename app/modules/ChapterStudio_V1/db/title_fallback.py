"""public.slide 제목 fallback 생성 유틸."""
from __future__ import annotations

import re
from html.parser import HTMLParser

from app.modules.ChapterStudio_V1.pipeline.state import StateRecord

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9+#/.-]{2,}")
_PUNCT_RE = re.compile(r"[.!?。！？\n]")
_INTRO_RE = re.compile(r"^(?:안녕하세요|안녕|반갑습니다|반가워요|다들\s*안녕|자)[,\s.]*")
_STOP_WORDS = {
    "이번",
    "화면",
    "슬라이드",
    "번째",
    "오늘",
    "우리",
    "여기",
    "먼저",
    "이제",
    "다음",
    "안녕하세",
}


def slide_title_from_context(
    draft: StateRecord | None,
    slide: StateRecord,
    voice: StateRecord,
    outline: StateRecord | None,
    chapter_title: str,
    idx: int,
) -> str:
    """명시 title 우선, 없으면 화면·대본·outline에서 짧은 제목을 만든다."""
    return meaningful_slide_title(_text(draft, "title"), chapter_title, idx, *_fallback_sources(draft, slide, voice, outline))


def meaningful_slide_title(raw_title: str, chapter_title: str, idx: int, *content_sources: str) -> str:
    """제네릭 제목이면 내용 후보에서 의미 있는 짧은 제목을 결정한다."""
    explicit = _title_candidate(raw_title, chapter_title, idx)
    if explicit:
        return explicit[:200]
    for source in content_sources:
        phrase = _phrase_from_text(source)
        if phrase:
            return phrase[:200]
    return f"{chapter_title} {idx + 1}"[:200]


def _fallback_sources(
    draft: StateRecord | None,
    slide: StateRecord,
    voice: StateRecord,
    outline: StateRecord | None,
) -> list[str]:
    return [
        _text(draft, "focus"),
        _text(draft, "narration"),
        _strip_html(_text(draft, "html")),
        _strip_html(_text(slide, "html_content")),
        _text(outline, "role"),
        _text(outline, "summary"),
        _text(voice, "script_text"),
    ]


def _title_candidate(title: str, chapter_title: str, idx: int) -> str:
    normalized = " ".join(title.split())
    if not normalized or _is_placeholder(normalized, chapter_title, idx):
        return ""
    return normalized


def _is_placeholder(title: str, chapter_title: str, idx: int) -> bool:
    chapter_pattern = rf"{re.escape(chapter_title)}\s*\d+"
    if re.fullmatch(chapter_pattern, title):
        return True
    if title in {f"슬라이드 {idx}", f"슬라이드 {idx + 1}"}:
        return True
    return bool(re.fullmatch(r"슬라이드\s*\d+", title))


def _phrase_from_text(text: str) -> str:
    first_sentence = _INTRO_RE.sub("", _PUNCT_RE.split(text.strip(), maxsplit=1)[0])
    words = [_clean_token(token) for token in _TOKEN_RE.findall(first_sentence)]
    kept = [word for word in words if _is_title_word(word)]
    return _fit_title(kept)


def _clean_token(token: str) -> str:
    return re.sub(r"(입니다|합니다|나요|요|은|는|이|가|을|를|의|에서|으로|로)$", "", token)


def _is_title_word(word: str) -> bool:
    return len(word) >= 2 and word not in _STOP_WORDS and not word.isdigit()


def _fit_title(words: list[str]) -> str:
    picked: list[str] = []
    for word in words:
        candidate = " ".join([*picked, word])
        if len(candidate) > 24:
            break
        picked.append(word)
        if len(picked) == 4:
            break
    return " ".join(picked)


def _text(row: StateRecord | None, key: str) -> str:
    if row is None:
        return ""
    value = row.get(key)
    return value if isinstance(value, str) else ""


def _strip_html(html: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(html)
    return " ".join(parser.parts)


class _HtmlTextExtractor(HTMLParser):
    """HTML 태그 밖 의미 텍스트만 제목 후보로 모은다."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


__all__ = ["meaningful_slide_title", "slide_title_from_context"]
