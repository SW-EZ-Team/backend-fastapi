"""하이픈 복원 — 줄 끝 하이픈으로 분리된 단어를 원래대로 이어붙인다.

영어 조판에서 행 끝에 단어가 하이픈으로 분리되는 경우(예: infor-\nmation)가
많다. 한국어 음절도 드물게 분리되므로 한글 범위도 처리한다.
"""
from __future__ import annotations

import re

# 영어 단어가 줄 끝 하이픈으로 분리된 패턴
_EN_HYPHEN_RE = re.compile(r"([A-Za-z])-\n([A-Za-z])")
# 한글 음절이 줄 끝에서 분리된 패턴 (드문 케이스)
_KO_HYPHEN_RE = re.compile(r"([가-힯])-\n([가-힯])")
# 소프트 하이픈(U+00AD)으로 분리된 패턴
_SOFT_HYPHEN_RE = re.compile(r"­\n")


def restore_hyphens(text: str) -> str:
    """하이픈으로 분리된 단어를 복원한다.

    순수 함수 — 입력을 변경하지 않고 새 문자열을 반환한다.
    """
    # 소프트 하이픈 제거 후 줄 이어붙이기
    result = _SOFT_HYPHEN_RE.sub("", text)
    # 영어 하이픈 복원
    result = _EN_HYPHEN_RE.sub(r"\1\2", result)
    # 한글 하이픈 복원
    result = _KO_HYPHEN_RE.sub(r"\1\2", result)
    return result
