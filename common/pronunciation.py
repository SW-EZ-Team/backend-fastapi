"""TTS용 기술 용어 발음 정규화."""
from __future__ import annotations

import re

_TERM_READINGS: dict[str, str] = {
    "async": "어싱크",
    "await": "어웨이트",
    "borrow": "보로우",
    "borrowing": "보로잉",
    "cargo": "카고",
    "clone": "클론",
    "compiler": "컴파일러",
    "copy": "카피",
    "closure": "클로저",
    "crate": "크레이트",
    "drop": "드롭",
    "enum": "이넘",
    "expect": "익스펙트",
    "hashmap": "해시맵",
    "impl": "임플",
    "iterator": "이터레이터",
    "lifetime": "라이프타임",
    "macro": "매크로",
    "match": "매치",
    "move": "무브",
    "mutex": "뮤텍스",
    "mutable": "뮤터블",
    "option": "옵션",
    "ownership": "오너십",
    "panic": "패닉",
    "reference": "레퍼런스",
    "result": "리절트",
    "rust": "러스트",
    "slice": "슬라이스",
    "string": "스트링",
    "struct": "스트럭트",
    "thread": "스레드",
    "trait": "트레이트",
    "unwrap": "언랩",
    "vec": "벡",
    "vector": "벡터",
}

_TERM_RE = re.compile(
    r"(?<![A-Za-z0-9_])("
    + "|".join(sorted((re.escape(term) for term in _TERM_READINGS), key=len, reverse=True))
    + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def normalize_pronunciation_terms(text: str) -> str:
    """영문 기술 용어를 한국어 발화형으로 바꾼다."""
    return _TERM_RE.sub(lambda match: _TERM_READINGS[match.group(1).lower()], text)
