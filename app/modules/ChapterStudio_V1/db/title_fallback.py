"""public.slide 제목 fallback 생성 유틸."""
from __future__ import annotations

import re
from html import unescape

from app.modules.ChapterStudio_V1.pipeline.state import StateRecord

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9+#/.-]{2,}")
_PUNCT_RE = re.compile(r"[.!?。！？\n]")
_HEADING_RE = re.compile(r"<(h[12])\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_MEANING_RE = re.compile(r"[가-힣0-9]")
_INTRO_RE = re.compile(
    r"^\s*(?:안녕하세요|안녕|반갑습니다|반가워요|다들\s*안녕|"
    r"튜터야|얘들아|여러분|방금|앞서|지난번에?|아까|앞에서|"
    r"오늘은?|이제|그럼|그러면|먼저|자)\s*[,!?.，。！？:：;-]*\s*"
)
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
    "튜터야",
    "얘들아",
    "여러분",
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
        heading = extract_heading_title(source)
        if heading:
            return heading[:200]
    for source in _phrase_sources(content_sources):
        phrase = _phrase_from_text(source)
        if phrase:
            return phrase[:200]
    return f"{chapter_title} {idx + 1}"[:200]


def extract_heading_title(html: str) -> str:
    """렌더 HTML의 첫 h1/h2를 안전한 슬라이드 제목 후보로 추출한다."""
    source = _decode_heading_source(html)
    match = _HEADING_RE.search(source)
    if match is None:
        return ""
    title = _normalize_space(_TAG_RE.sub(" ", unescape(match.group(2))))
    if 6 <= len(title) <= 40 and _TITLE_MEANING_RE.search(title):
        return title
    return ""


def _fallback_sources(
    draft: StateRecord | None,
    slide: StateRecord,
    voice: StateRecord,
    outline: StateRecord | None,
) -> list[str]:
    return [
        _text(draft, "focus"),
        _text(draft, "narration"),
        _text(voice, "script_text"),
        _text(outline, "role"),
        _text(outline, "summary"),
        _text(draft, "html"),
        _text(slide, "html_content"),
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
    for sentence in _sentences(text):
        words = [_clean_token(token) for token in _TOKEN_RE.findall(_strip_intro(sentence))]
        kept = [word for word in words if _is_title_word(word)]
        if kept:
            return _fit_title(kept)
    return ""


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _PUNCT_RE.split(text.strip()) if part.strip()]


def _phrase_sources(content_sources: tuple[str, ...]) -> list[str]:
    html_sources = [_strip_html(_decode_heading_source(source)) for source in content_sources if _looks_like_html(source)]
    text_sources = [source for source in content_sources if not _looks_like_html(source)]
    return [source for source in [*text_sources, *html_sources] if source.strip()]


def _strip_intro(sentence: str) -> str:
    stripped = sentence.strip()
    previous = ""
    while stripped and stripped != previous:
        previous = stripped
        stripped = _INTRO_RE.sub("", stripped).strip()
    return stripped


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


def _decode_heading_source(source: str) -> str:
    return unescape(source) if "&lt;" in source else source


def _looks_like_html(source: str) -> bool:
    return "<" in source or "&lt;" in source


def _strip_html(html: str) -> str:
    return _normalize_space(_TAG_RE.sub(" ", html))


def _normalize_space(text: str) -> str:
    return " ".join(text.split())


__all__ = ["extract_heading_title", "meaningful_slide_title", "slide_title_from_context"]
