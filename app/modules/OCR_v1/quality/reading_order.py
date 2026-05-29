"""읽기 순서 품질 점수 측정 — 마크다운 구조의 논리적 일관성을 검사한다.

OCR 이 컬럼 레이아웃이나 조판 요소를 잘못 인식하면 문단이 뒤섞이거나
헤딩 계층이 무너진다. 이 함수로 그 정도를 정량화한다.
"""
from __future__ import annotations

import re

# 헤딩 패턴 — #의 수로 레벨을 결정
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
# 문단 끝에 '-'가 붙어 다음 줄로 이어지는 비정상 분리
_BROKEN_PARA_RE = re.compile(r"\w-\n\w")
# 목록 항목
_LIST_ITEM_RE = re.compile(r"^(\s*[-*+]|\s*\d+\.)\s", re.MULTILINE)


def _check_heading_hierarchy(lines: list[str]) -> float:
    """헤딩 계층이 순서대로 내려가는지 검사한다.

    H1 없이 H2 가 먼저 나오거나 H2 없이 H3 가 나오는 경우 감점한다.
    """
    headings = _HEADING_RE.findall("\n".join(lines))
    if not headings:
        return 1.0  # 헤딩 없는 문서는 순서 위반 없음

    violations = 0
    prev_level = 0
    for marker, _ in headings:
        level = len(marker)
        # 레벨이 한 번에 2단계 이상 건너뛰는 경우를 위반으로 간주
        if level > prev_level + 1 and prev_level > 0:
            violations += 1
        prev_level = level

    return max(0.0, 1.0 - violations / max(len(headings), 1))


def _check_broken_paragraphs(text: str) -> float:
    """줄 끝 하이픈으로 인한 단어 분리 비율을 측정한다.

    hyphen_restore 후처리 전에 실행하므로 이 패턴이 많으면 감점한다.
    """
    broken = len(_BROKEN_PARA_RE.findall(text))
    # 단락 수 대비 비율로 환산 (단락이 없으면 1.0)
    paragraphs = max(text.count("\n\n"), 1)
    ratio = broken / paragraphs
    return max(0.0, 1.0 - ratio)


def _check_list_continuity(lines: list[str]) -> float:
    """목록 항목이 의미 없이 중단되는지 검사한다.

    목록 블록 내에서 빈 줄 없이 목록이 아닌 줄이 삽입되면 감점한다.
    """
    in_list = False
    interruptions = 0
    list_blocks = 0

    for line in lines:
        is_list_item = bool(_LIST_ITEM_RE.match(line))
        if is_list_item:
            in_list = True
        elif in_list and line.strip() and not is_list_item:
            # 빈 줄이 아니면서 목록 항목도 아닌 줄이 목록 중간에 삽입됨
            interruptions += 1
            in_list = False
            list_blocks += 1
        elif not line.strip():
            in_list = False

    if list_blocks == 0:
        return 1.0
    return max(0.0, 1.0 - interruptions / list_blocks)


def score_reading_order(markdown: str) -> tuple[float, str]:
    """읽기 순서 품질 점수와 이유를 반환한다.

    반환: (score 0.0~1.0, reason 문자열)
    """
    if not markdown.strip():
        return 1.0, "empty"

    lines = markdown.splitlines()
    h_score = _check_heading_hierarchy(lines)
    p_score = _check_broken_paragraphs(markdown)
    l_score = _check_list_continuity(lines)

    # 세 지표를 동일 가중치로 평균
    score = (h_score + p_score + l_score) / 3.0
    reason = "ok" if score >= 0.8 else f"h={h_score:.2f},p={p_score:.2f},l={l_score:.2f}"
    return round(score, 4), reason
