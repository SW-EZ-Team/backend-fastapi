"""헤더·푸터 제거 — 페이지 경계에 반복 나타나는 텍스트를 삭제한다.

논문·교재의 페이지 번호, 챕터 제목, 저작권 문구 등이 여러 페이지에 걸쳐
반복될 때 마크다운에 불필요한 잡음으로 남는다. 이를 제거해 청킹 품질을 높인다.
"""
from __future__ import annotations

import re

# 페이지 번호 패턴 — 숫자만 있는 단독 줄, 또는 - 1 - 형식
_PAGE_NUM_RE = re.compile(r"^\s*[-–—]?\s*\d+\s*[-–—]?\s*$", re.MULTILINE)
# 연속으로 등장하는 짧은 줄 (헤더/푸터 후보)
_SHORT_LINE_RE = re.compile(r"^.{1,80}$")

# 동일 줄이 이 횟수 이상 반복되면 헤더/푸터로 간주
_REPEAT_THRESHOLD = 2


def _find_repeated_lines(text: str) -> set[str]:
    """2회 이상 등장하는 짧은 줄을 헤더/푸터 후보로 반환한다."""
    lines = text.splitlines()
    counts: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and _SHORT_LINE_RE.match(stripped) and len(stripped) < 80:
            counts[stripped] = counts.get(stripped, 0) + 1
    return {line for line, cnt in counts.items() if cnt >= _REPEAT_THRESHOLD}


def remove_headers_footers(markdown: str) -> str:
    """마크다운 텍스트에서 헤더·푸터와 페이지 번호를 제거한다.

    순수 함수 — 입력을 변경하지 않고 새 문자열을 반환한다.
    """
    # 페이지 번호 행 제거
    result = _PAGE_NUM_RE.sub("", markdown)

    # 반복 헤더/푸터 행 제거
    repeated = _find_repeated_lines(result)
    if repeated:
        lines = result.splitlines()
        cleaned = [
            line for line in lines
            if line.strip() not in repeated
        ]
        result = "\n".join(cleaned)

    # 3개 이상 연속 빈 줄을 2개로 압축
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result
