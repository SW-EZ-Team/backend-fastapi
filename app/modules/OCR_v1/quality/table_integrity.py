"""표 무결성 품질 점수 측정 — 마크다운 표의 구조적 일관성을 검사한다.

OCR 이 표를 잘못 인식하면 열 수가 행마다 달라지거나 구분선이 누락된다.
이 함수로 표의 완성도를 정량화해 품질 게이트 판단에 사용한다.
"""
from __future__ import annotations

import re

# 마크다운 표 행 패턴 — 앞뒤 파이프 선택적
_TABLE_ROW_RE = re.compile(r"^\|?.+\|.+\|?$")
# 구분선 행 (헤더와 본문 사이)
_SEPARATOR_RE = re.compile(r"^\|?[\s\-:|]+\|[\s\-:|]+\|?$")


def _extract_table_blocks(markdown: str) -> list[list[str]]:
    """마크다운에서 표 블록을 추출한다. 블록 = 연속된 표 행 목록."""
    blocks: list[list[str]] = []
    current: list[str] = []

    for line in markdown.splitlines():
        if _TABLE_ROW_RE.match(line.strip()):
            current.append(line.strip())
        else:
            if current:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)
    return blocks


def _col_count(row: str) -> int:
    """표 행의 열 수를 계산한다."""
    stripped = row.strip("|")
    return len(stripped.split("|"))


def _score_single_block(block: list[str]) -> float:
    """단일 표 블록의 무결성 점수를 반환한다 (0.0~1.0)."""
    if len(block) < 2:
        # 헤더만 있고 내용이 없는 표는 감점하지 않음
        return 1.0

    # 구분선 존재 여부 확인 (두 번째 행이 구분선이어야 정규 마크다운 표)
    has_separator = _SEPARATOR_RE.match(block[1]) is not None

    # 기준 열 수: 첫 번째 행(헤더)
    expected_cols = _col_count(block[0])
    if expected_cols == 0:
        return 0.0

    violations = 0
    empty_cells = 0
    total_cells = 0

    for row in block:
        if _SEPARATOR_RE.match(row):
            continue
        cols = row.split("|")
        cols = [c for c in cols if c != ""]  # 앞뒤 빈 요소 제거

        # 열 수 불일치
        if len(cols) != expected_cols:
            violations += 1

        # 빈 셀 비율 측정
        for cell in cols:
            total_cells += 1
            if not cell.strip():
                empty_cells += 1

    col_consistency = 1.0 - violations / max(len(block), 1)
    empty_ratio = empty_cells / max(total_cells, 1)
    separator_bonus = 0.1 if has_separator else 0.0

    score = col_consistency * 0.6 + (1.0 - empty_ratio) * 0.3 + separator_bonus
    return min(max(score, 0.0), 1.0)


def score_table_integrity(markdown: str, tables: list[dict]) -> tuple[float, str]:
    """표 무결성 점수와 이유를 반환한다.

    markdown 에서 직접 표를 파싱하고 tables 메타데이터와 교차 검증한다.
    반환: (score 0.0~1.0, reason 문자열)
    """
    blocks = _extract_table_blocks(markdown)

    if not blocks and not tables:
        return 1.0, "no_tables"

    if not blocks:
        # 메타데이터에는 표가 있지만 마크다운에서 못 찾음 — 부분 감점
        return 0.7, "tables_in_meta_not_in_md"

    scores = [_score_single_block(b) for b in blocks]
    avg = sum(scores) / len(scores)
    reason = "ok" if avg >= 0.8 else f"avg={avg:.2f},blocks={len(blocks)}"
    return round(avg, 4), reason
