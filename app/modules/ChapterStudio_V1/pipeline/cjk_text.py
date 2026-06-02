from __future__ import annotations

import re

from app.modules.ChapterStudio_V1.common.logging import logger

CJK_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\U00020000-\U0002EBEF぀-ヿ]+")
_SPACE_RE = re.compile(r"\s+")
_PUNCT_SPACE_RE = re.compile(r"\s+([,.!?;:，。！？；：])")


def strip_cjk(text: str) -> str:
    """TTS 오발음을 막기 위해 한자·가나 런을 제거하고 공백만 정리한다."""
    matches = CJK_RE.findall(text)
    if not matches:
        return text
    logger.warning("CJK 문자 제거: {}", _unique_removed_text(matches))
    without_cjk = CJK_RE.sub(" ", text)
    return _cleanup_cjk_spacing(without_cjk)


def _unique_removed_text(matches: list[str]) -> str:
    seen: set[str] = set()
    kept: list[str] = []
    for text in matches:
        for char in text:
            if char not in seen:
                seen.add(char)
                kept.append(char)
    return "".join(kept)


def _cleanup_cjk_spacing(text: str) -> str:
    compact = _SPACE_RE.sub(" ", text)
    compact = _PUNCT_SPACE_RE.sub(r"\1", compact)
    return compact.strip()


__all__ = ["CJK_RE", "strip_cjk"]
