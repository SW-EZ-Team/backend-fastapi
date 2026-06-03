"""제목(title) 규칙의 단일 진실 소스.

'챕터명+번호' 형태 제목 감지·재라벨 로직을 한 곳에 둔다. 이전에는 parallel_prompts와
visual_quality에 정규식이 중복 정의돼 있었으나(드리프트 위험), 이 모듈로 통합한다.

감지 대상(재라벨해야 하는 나쁜 제목):
    - '수직선과 정수의 위치 3'  : 본문+공백+숫자(챕터 순번)
    - '3단원 2번'               : 끝이 '번'으로 끝나는 순번
    - '함수 개념 5장'           : 끝이 '장/단원/차시'로 끝나는 순번

비대상(정상 제목 — 재라벨 금지):
    - '음수끼리의 크기 비교'     : 순번 없음
    - '일차함수 y=ax+b'         : 수식(=,+ 등) 포함 — 수식 제목 과잉매칭 방지
    - '이차방정식 x^2=4의 해'    : 수식 포함
"""
from __future__ import annotations

import re

# 수식·연산 기호 — 이 기호가 제목에 있으면 수식 제목으로 보고 챕터-순번 매칭에서 제외한다.
# (예: 'y=ax+b 12'를 챕터 순번으로 오인하지 않게 한다)
_FORMULA_MARKER_RE = re.compile(r"[=^√∑∫×÷±≤≥≠]|\b\d+\s*[+\-*/]\s*\d+\b")

# 끝이 챕터 순번(숫자 + 선택적 단위어)으로 끝나는 제목.
# - 숫자 앞에는 공백이 있어야 한다(본문과 순번 분리).
# - 숫자 뒤 단위어(번/단원/장/차시/강/회)는 선택. 단위어가 있으면 숫자 앞 공백은 선택.
# 예: '... 위치 3', '3단원 2번', '함수 5장'
_CHAPTER_ORDINAL_RE = re.compile(
    r"^.{2,}?"                       # 앞에 최소 2자 본문(너무 짧은 제목 제외)
    r"(?:\s+\d{1,2}|\d{1,2}(?:번|단원|장|차시|강|회))$"
)


def is_chapter_number_title(title: str) -> bool:
    """제목이 '챕터명+번호' 형태인지 판정한다(재라벨 대상 여부).

    수식 기호가 있으면 수식 제목으로 보고 False(과잉매칭 방지).
    그 외에 끝이 챕터 순번으로 끝나면 True.
    """
    stripped = title.strip()
    if not stripped:
        return False
    if _FORMULA_MARKER_RE.search(stripped):
        # 수식 제목은 끝 숫자가 챕터 순번이 아니라 식의 일부이므로 재라벨하지 않는다.
        return False
    return bool(_CHAPTER_ORDINAL_RE.match(stripped))


def relabel_chapter_title(title: str, must_have: list[str] | None) -> str:
    """챕터명+번호 형태 제목을 must_have 첫 항목 기반으로 결정적 재라벨한다.

    is_chapter_number_title이 True이고 must_have가 있으면 must_have[0]을 16자 이내로 잘라
    교체한다. 대상이 아니거나 must_have가 없으면 원본 제목을 유지한다.
    동일 입력 → 동일 출력(재현성 보장, AI 미관여).
    """
    if not is_chapter_number_title(title):
        return title
    if not must_have:
        return title
    concept = str(must_have[0])[:16].strip()
    return concept if concept else title


__all__ = ["is_chapter_number_title", "relabel_chapter_title"]
