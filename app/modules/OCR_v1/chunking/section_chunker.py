"""섹션 기반 청킹 — 마크다운 헤딩 계층으로 문서를 청크로 분할한다.

섹션이 너무 크면 단락 경계에서 추가 분할하고, 너무 작으면 다음 섹션과 병합한다.
표·수식은 속한 섹션의 청크와 함께 이동해 RAG 문맥 보존을 극대화한다.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field

import tiktoken

from .. import config as cfg

_LOG = logging.getLogger(__name__)
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
_TABLE_RE = re.compile(r"^\|.+\|$", re.MULTILINE)
_FORMULA_RE = re.compile(r"\$\$.+?\$\$|\$[^$\n]+\$", re.DOTALL)
_TOKENIZER = tiktoken.get_encoding("cl100k_base")


@dataclass
class _Section:
    """내부 섹션 표현 — 청킹 전 중간 데이터 구조."""

    title: str
    level: int
    content: str
    page_nums: list[int] = field(default_factory=list)


def _count_tokens(text: str) -> int:
    """tiktoken 으로 토큰 수를 계산한다 (30자 내외 순수 함수)."""
    return len(_TOKENIZER.encode(text))


def _extract_page_nums(pages: list[dict], start: int, end: int) -> list[int]:
    """마크다운 오프셋 범위에 해당하는 페이지 번호 목록을 반환한다."""
    # 각 PageExtraction 의 markdown 길이 누적합으로 페이지를 추정
    nums: list[int] = []
    offset = 0
    for p in pages:
        md = p.get("markdown", "")
        p_end = offset + len(md)
        if offset <= end and p_end >= start:
            nums.append(p["page_num"])
        offset = p_end
    return sorted(set(nums)) if nums else [pages[0]["page_num"]] if pages else []


def _split_by_paragraphs(text: str, max_tok: int) -> list[str]:
    """텍스트를 단락 경계에서 max_tok 이하 청크로 분할한다."""
    paragraphs = re.split(r"\n\n+", text)
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = (current + "\n\n" + para).strip() if current else para
        if _count_tokens(candidate) > max_tok and current:
            chunks.append(current.strip())
            current = para
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text]


def _parse_sections(markdown: str) -> list[_Section]:
    """마크다운을 헤딩 경계로 섹션 목록으로 파싱한다."""
    matches = list(_HEADING_RE.finditer(markdown))
    sections: list[_Section] = []

    if not matches:
        # 헤딩 없는 문서 전체를 하나의 섹션으로 처리
        sections.append(_Section(title="본문", level=1, content=markdown))
        return sections

    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        content = markdown[start:end].strip()
        sections.append(_Section(title=title, level=level, content=content))

    return sections


def _make_chunk_id(filename: str, section_title: str, idx: int) -> str:
    """청크 고유 ID 를 생성한다."""
    raw = f"{filename}:{section_title}:{idx}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class SectionChunker:
    """섹션 기반 청킹 — Chunker Protocol 구현체."""

    async def chunk(self, markdown: str, pages: list[dict]) -> list[dict]:
        """마크다운을 청크 딕셔너리 목록으로 분할한다.

        pages 는 PageExtraction 형식 딕셔너리 목록이다.
        """
        min_tok = cfg.chunk_min_tokens()
        max_tok = cfg.chunk_max_tokens()
        filename = pages[0].get("engine", "unknown") if pages else "unknown"

        sections = _parse_sections(markdown)
        merged: list[_Section] = []

        # 너무 작은 섹션은 다음 섹션과 병합
        for sec in sections:
            if merged and _count_tokens(sec.content) < min_tok:
                prev = merged[-1]
                prev.content += "\n\n" + sec.content
                prev.page_nums.extend(sec.page_nums)
            else:
                merged.append(sec)

        records: list[dict] = []
        offset = 0
        for sec in merged:
            sub_texts = (
                _split_by_paragraphs(sec.content, max_tok)
                if _count_tokens(sec.content) > max_tok
                else [sec.content]
            )

            for i, text in enumerate(sub_texts):
                pg_nums = _extract_page_nums(pages, offset, offset + len(text))
                tables = [m.group(0) for m in _TABLE_RE.finditer(text)]
                formulas = _FORMULA_RE.findall(text)
                records.append({
                    "chunk_id": _make_chunk_id(filename, sec.title, len(records)),
                    "text": text,
                    "token_count": _count_tokens(text),
                    "section_title": sec.title,
                    "section_level": sec.level,
                    "page_nums": pg_nums,
                    "tables": [{"md": t} for t in tables],
                    "formulas": formulas,
                })
                offset += len(text)

        _LOG.info("청킹 완료: %d개 섹션 → %d개 청크", len(merged), len(records))
        return records
