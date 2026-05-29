"""OCR 잔여물과 불필요 형식을 제거하는 텍스트 클리너."""
from __future__ import annotations

import re
from collections import Counter

# 페이지 번호 패턴들
_PAGE_DASH_RE = re.compile(r"^\s*[-–—]\s*\d+\s*[-–—]\s*$", re.MULTILINE)
_PAGE_BRACKET_RE = re.compile(r"^\s*\[?\d+\]?\s*$", re.MULTILINE)
_PAGE_P_RE = re.compile(r"^\s*p\.?\s*\d+\s*$", re.MULTILINE)

# OCR 잔여 특수문자 패턴
_BOX_CHARS_RE = re.compile(r"[│─┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩═║]")
_REPEATED_SPECIAL_RE = re.compile(r"([#*=\-_~^])\1{2,}")
_REPLACEMENT_CHAR_RE = re.compile(r"�+")

# 줄바꿈이 문장 중간에서 발생하는 경우 탐지 (마침표/물음표/느낌표가 없는 줄 끝)
_BROKEN_LINE_RE = re.compile(
    r"([^\.\?!。？！\n])\n([^\n\-\*\d•])",
    re.MULTILINE,
)

# 연속 줄바꿈 정리: 3개 이상 → 2개
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
# 연속 공백 정리: 2개 이상 → 1개
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
# 탭 → 공백
_TAB_RE = re.compile(r"\t")


def clean_text(text: str) -> str:
    """OCR 잔여물과 불필요 형식을 제거한 정제 텍스트 반환."""
    text = remove_page_numbers(text)
    text = remove_headers_footers(text)
    text = fix_broken_lines(text)
    text = remove_ocr_artifacts(text)
    text = collapse_whitespace(text)
    return text.strip()


def remove_page_numbers(text: str) -> str:
    """페이지 번호 패턴을 제거한다.

    지원 패턴: '- 3 -', '[3]', 'p.3', 'p 3' 형태의 독립 줄.
    """
    text = _PAGE_DASH_RE.sub("", text)
    text = _PAGE_BRACKET_RE.sub("", text)
    text = _PAGE_P_RE.sub("", text)
    return text


def remove_headers_footers(text: str) -> str:
    """3회 이상 정확히 동일한 줄이 반복되면 헤더/푸터로 간주해 제거."""
    lines = text.splitlines()
    # 비어 있지 않은 줄의 등장 횟수 집계
    freq = Counter(ln.strip() for ln in lines if ln.strip())
    # 3회 이상 동일하게 반복되는 줄은 제거 대상
    repeated = {line for line, count in freq.items() if count >= 3}
    if not repeated:
        return text
    filtered = [ln for ln in lines if ln.strip() not in repeated]
    return "\n".join(filtered)


def fix_broken_lines(text: str) -> str:
    """OCR에서 문장 중간에 삽입된 불필요 줄바꿈을 공백으로 연결."""
    # 마침표·물음표·느낌표 없이 끝난 줄 + 다음 줄 소문자/한글 시작 → 공백 연결
    return _BROKEN_LINE_RE.sub(r"\1 \2", text)


def remove_ocr_artifacts(text: str) -> str:
    """OCR 잔여 특수문자를 제거한다.

    제거 대상: 박스 문자, 연속 특수문자(###, *** 등), 유니코드 대체 문자(U+FFFD).
    """
    text = _BOX_CHARS_RE.sub("", text)
    text = _REPEATED_SPECIAL_RE.sub("", text)
    text = _REPLACEMENT_CHAR_RE.sub("", text)
    return text


def collapse_whitespace(text: str) -> str:
    """연속 공백·줄바꿈을 정리하고 탭을 공백으로 변환."""
    text = _TAB_RE.sub(" ", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text
