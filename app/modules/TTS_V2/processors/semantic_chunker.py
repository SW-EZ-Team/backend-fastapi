"""의미 경계를 기준으로 텍스트를 TTS 청크로 분할하는 모듈.

V1의 split_tts_segments 구조를 계승하되, 섹션 단위 처리와
청크 메타데이터 생성을 추가한다.
"""
from __future__ import annotations

import re

# 한국어 문장 종결 구두점 (소수점 분리 방지 포함)
_SENTENCE_END_RE = re.compile(
    # 소수점(숫자.숫자)은 분리하지 않기 위해 뒤에 숫자가 없을 때만 매칭
    r"(?<!\d)[.。](?!\d)|[!?！？]"
)
# 약어 패턴 (Mr., Dr., 등) — 문장 경계에서 제외
_ABBR_DOT_RE = re.compile(r"\b(Mr|Dr|Ms|Prof|Sr|Jr|vs|etc|cf)\.")
# 절 단위 분리자
_CLAUSE_SEP_RE = re.compile(r"[,，;；:：]")


def chunk_sections(
    sections: list[dict],
    min_chars: int = 40,
    max_chars: int = 120,
) -> list[dict]:
    """섹션 목록을 TTS 청크로 분할.

    skip=True인 섹션은 완전히 제외한다.
    """
    chunks: list[dict] = []
    for section_idx, section in enumerate(sections):
        # skip 섹션(코드블록, 테이블, 각주)은 TTS에서 낭독하지 않음
        if section.get("skip", False):
            continue
        section_chunks = split_section_to_chunks(
            section.get("text", ""),
            section.get("title", ""),
            section_idx,
            min_chars=min_chars,
            max_chars=max_chars,
        )
        chunks.extend(section_chunks)
    return chunks


def split_section_to_chunks(
    text: str,
    title: str,
    section_idx: int,
    min_chars: int = 40,
    max_chars: int = 120,
) -> list[dict]:
    """단일 섹션 텍스트를 3단계 계층으로 청크 분할.

    1단계: 문장 경계 분할
    2단계: 짧은 문장 병합
    3단계: 긴 문장 절 단위 분할
    """
    sentences = split_by_sentences(text)
    chunks_text = merge_and_split_sentences(sentences, min_chars, max_chars)
    return [
        {
            "chunk_id": f"ch_{section_idx:03d}_{i:03d}",
            "chapter_idx": section_idx,
            "section_title": title,
            "original_text": chunk_text,
            "normalized_text": "",   # text_normalizer 적용 후 채워짐
            "planned_text": "",      # LLM plan_reading_node 적용 후 채워짐
        }
        for i, chunk_text in enumerate(chunks_text)
    ]


def split_by_sentences(text: str) -> list[str]:
    """문장 종결 구두점 기준으로 텍스트를 문장 단위로 분할.

    소수점("3.14"), 약어("Mr.") 등은 분리하지 않는다.
    """
    # 약어 뒤 마침표를 임시 치환해 분리 방지
    placeholder = "\x00"
    protected = _ABBR_DOT_RE.sub(lambda m: m.group(0).replace(".", placeholder), text)

    # 문장 종결 구두점 위치로 분할
    parts: list[str] = []
    prev = 0
    for m in _SENTENCE_END_RE.finditer(protected):
        end = m.end()
        part = protected[prev:end].replace(placeholder, ".").strip()
        if part:
            parts.append(part)
        prev = end
    # 남은 미종결 텍스트 (마지막 문장이 구두점 없는 경우)
    remainder = protected[prev:].replace(placeholder, ".").strip()
    if remainder:
        parts.append(remainder)
    return [p for p in parts if p]


def merge_and_split_sentences(
    sentences: list[str],
    min_chars: int,
    max_chars: int,
) -> list[str]:
    """짧은 문장 병합 + 긴 문장 절 단위 분할."""
    # 1단계: 먼저 긴 문장을 절 단위로 분할
    expanded: list[str] = []
    for sent in sentences:
        if len(sent) > max_chars:
            expanded.extend(_split_long_sentence(sent, max_chars))
        else:
            expanded.append(sent)

    if not expanded:
        return []

    # 2단계: min_chars 미만 문장을 다음 문장과 병합
    merged: list[str] = []
    buffer = expanded[0]
    for piece in expanded[1:]:
        candidate = f"{buffer} {piece}"
        if len(buffer) < min_chars and len(candidate) <= max_chars:
            # 짧은 버퍼를 다음 문장과 합침
            buffer = candidate
        else:
            merged.append(buffer)
            buffer = piece
    merged.append(buffer)
    return [m.strip() for m in merged if m.strip()]


def _split_long_sentence(text: str, max_chars: int) -> list[str]:
    """max_chars를 초과하는 문장을 절 경계 → 공백 순으로 분할."""
    if len(text) <= max_chars:
        return [text.strip()]

    # 절 단위 시도 (쉼표, 세미콜론, 콜론)
    clauses = [c.strip() for c in _CLAUSE_SEP_RE.split(text) if c.strip()]
    if len(clauses) > 1:
        pieces = _merge_pieces(clauses, max_chars)
        if all(len(p) <= max_chars for p in pieces):
            return pieces

    # 절 단위로도 불가 시 단어 경계로 강제 분할
    return _chunk_by_words(text, max_chars)


def _merge_pieces(pieces: list[str], max_chars: int) -> list[str]:
    """조각 목록을 max_chars 이내로 탐욕적으로 병합."""
    result: list[str] = []
    current = ""
    for piece in pieces:
        candidate = piece if not current else f"{current}, {piece}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                result.append(current)
            current = piece
    if current:
        result.append(current)
    return result


def _chunk_by_words(text: str, max_chars: int) -> list[str]:
    """단어 경계 기준으로 강제 분할 (문장 중간 절단 최소화)."""
    words = text.split()
    result: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                result.append(current)
            current = word
    if current:
        result.append(current)
    return [r.strip() for r in result if r.strip()]
