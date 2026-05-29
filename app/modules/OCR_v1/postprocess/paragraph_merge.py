"""단락 병합 — 페이지 경계에서 분리된 단락을 이어붙인다.

OCR 이 페이지를 개별로 처리하면 한 문단이 두 페이지에 걸쳐 나뉘는 경우가 있다.
마크다운 특수 블록(헤딩, 목록, 표, 코드)은 보존하고 일반 텍스트만 병합한다.
"""
from __future__ import annotations

import re

# 병합에서 제외해야 하는 특수 블록 시작 패턴
_HEADING_RE = re.compile(r"^#{1,4}\s")
_LIST_RE = re.compile(r"^\s*[-*+]\s|^\s*\d+\.\s")
_TABLE_RE = re.compile(r"^\|")
_CODE_FENCE_RE = re.compile(r"^```")
_FORMULA_BLOCK_RE = re.compile(r"^\$\$")


def _is_special_line(line: str) -> bool:
    """특수 블록 시작 줄인지 판별한다."""
    stripped = line.strip()
    return bool(
        _HEADING_RE.match(stripped)
        or _LIST_RE.match(stripped)
        or _TABLE_RE.match(stripped)
        or _CODE_FENCE_RE.match(stripped)
        or _FORMULA_BLOCK_RE.match(stripped)
        or not stripped  # 빈 줄은 단락 구분자로 유지
    )


def merge_paragraphs(markdown: str) -> str:
    """페이지 경계에서 분리된 일반 텍스트 단락을 병합한다.

    마침표·물음표·느낌표로 끝나지 않은 줄 다음에 이어지는 일반 텍스트를
    동일 단락으로 간주해 줄바꿈을 제거한다.
    순수 함수 — 입력을 변경하지 않고 새 문자열을 반환한다.
    """
    lines = markdown.splitlines()
    result: list[str] = []
    in_code = False

    for i, line in enumerate(lines):
        # 코드 펜스 추적 — 코드 블록 내부는 변경하지 않음
        if _CODE_FENCE_RE.match(line.strip()):
            in_code = not in_code

        if in_code or _is_special_line(line):
            result.append(line)
            continue

        # 이전 줄이 있고, 문장 종결이 아닌 일반 텍스트인 경우 이어붙임
        if (
            result
            and result[-1].strip()
            and not _is_special_line(result[-1])
            and not result[-1].rstrip().endswith((".", "?", "!", ":", ";"))
        ):
            # 한글과 영문 사이의 불필요한 공백 없이 이어붙임
            result[-1] = result[-1].rstrip() + " " + line.lstrip()
        else:
            result.append(line)

    return "\n".join(result)
