"""마크다운 표 정규화 — Marker/MinerU 출력의 표 형식을 통일한다.

각 엔진마다 표 출력 방식이 미묘하게 달라 파이프 정렬·셀 공백 처리가 일관되지
않는 경우가 있다. 이 함수로 표를 표준 마크다운 형식으로 정규화한다.
"""
from __future__ import annotations

import re

_TABLE_ROW_RE = re.compile(r"^\|?.+\|.+\|?$")
_SEPARATOR_RE = re.compile(r"^\|?[\s\-:|]+\|[\s\-:|]+\|?$")


def _parse_cells(row: str) -> list[str]:
    """표 행에서 셀 목록을 파싱한다."""
    stripped = row.strip().strip("|")
    return [c.strip() for c in stripped.split("|")]


def _format_row(cells: list[str], widths: list[int]) -> str:
    """셀 목록을 지정 너비에 맞춰 패딩해 표 행 문자열을 생성한다."""
    padded = [cell.ljust(w) for cell, w in zip(cells, widths)]
    return "| " + " | ".join(padded) + " |"


def _normalize_block(block: list[str]) -> list[str]:
    """단일 표 블록을 정규화한다."""
    rows = [row for row in block if not _SEPARATOR_RE.match(row.strip())]
    if not rows:
        return block

    parsed = [_parse_cells(r) for r in rows]
    # 열 수를 최대값으로 통일 (짧은 행에 빈 셀 추가)
    max_cols = max(len(p) for p in parsed)
    normalized: list[list[str]] = []
    for cells in parsed:
        while len(cells) < max_cols:
            cells.append("")
        normalized.append(cells[:max_cols])

    # 열별 최대 너비 계산
    widths = [max(len(row[i]) for row in normalized) for i in range(max_cols)]
    widths = [max(w, 3) for w in widths]  # 구분선 최소 너비 3

    result: list[str] = []
    for i, cells in enumerate(normalized):
        result.append(_format_row(cells, widths))
        if i == 0:
            # 헤더 다음에 구분선 삽입
            separator = "| " + " | ".join("-" * w for w in widths) + " |"
            result.append(separator)
    return result


def normalize_tables(markdown: str) -> str:
    """마크다운 전체에서 표를 찾아 정규화한다.

    순수 함수 — 입력을 변경하지 않고 새 문자열을 반환한다.
    """
    lines = markdown.splitlines()
    result: list[str] = []
    block: list[str] = []

    for line in lines:
        if _TABLE_ROW_RE.match(line.strip()):
            block.append(line)
        else:
            if block:
                result.extend(_normalize_block(block))
                result.append("")
                block = []
            result.append(line)

    if block:
        result.extend(_normalize_block(block))

    return "\n".join(result)
