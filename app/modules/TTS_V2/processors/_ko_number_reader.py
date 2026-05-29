"""한국어 숫자 발화형 변환 전용 모듈.

정수·전화번호·날짜·연도·퍼센트·소수점·금액 패턴을
한국어 발화형 문자열로 교체하는 순수 함수 모음.
text_normalizer.py의 SRP 분리로 생성됨.
"""
from __future__ import annotations

import re

# ── 한국어 숫자 단위 상수 ────────────────────────────────
# 0~9 한국어 숫자 낱말 (인덱스 = 숫자값)
_KO_UNITS = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
# 자리 단위 (일, 십, 백, 천)
_KO_POS = ["", "십", "백", "천"]
# 큰 단위 (만, 억, 조)
_KO_LARGE = ["", "만", "억", "조"]


def _chunk_to_korean(n: int) -> str:
    """0~9999 범위 정수를 한국어 발화형으로 변환."""
    result = ""
    for pos in range(3, -1, -1):
        digit = (n // (10 ** pos)) % 10
        if digit == 0:
            continue
        # 1천·1백·1십은 '일' 생략 관용
        prefix = "" if (digit == 1 and pos > 0) else _KO_UNITS[digit]
        result += prefix + _KO_POS[pos]
    return result


def _int_to_korean(n: int) -> str:
    """정수를 한국어 발화형으로 변환 (최대 9999조)."""
    if n == 0:
        return "영"
    result = ""
    large_idx = 0
    while n > 0:
        chunk = n % 10000
        if chunk:
            result = _chunk_to_korean(chunk) + _KO_LARGE[large_idx] + result
        n //= 10000
        large_idx += 1
    return result


def _replace_phone(m: re.Match) -> str:
    """전화번호를 자리별 숫자 발음으로 변환."""
    def digits(s: str) -> str:
        return "".join(_KO_UNITS[int(c)] for c in s)
    return f"{digits(m.group(1))} {digits(m.group(2))} {digits(m.group(3))}"


def _replace_date(m: re.Match) -> str:
    """날짜(N월 N일)를 한국어 발화형으로 변환."""
    mo = _int_to_korean(int(m.group(1)))
    day = _int_to_korean(int(m.group(2)))
    return f"{mo}월 {day}일"


def _replace_year(m: re.Match) -> str:
    """연도를 한국어 발화형으로 변환."""
    return f"{_int_to_korean(int(m.group(1)))} 년"


def _replace_pct(m: re.Match) -> str:
    """퍼센트를 한국어 발화형으로 변환."""
    num_str = m.group(1)
    if "." in num_str:
        int_part, frac_part = num_str.split(".", 1)
        ko_int = _int_to_korean(int(int_part))
        ko_frac = "".join(_KO_UNITS[int(c)] for c in frac_part)
        return f"{ko_int} 점 {ko_frac} 퍼센트"
    return f"{_int_to_korean(int(num_str))} 퍼센트"


def _replace_decimal(m: re.Match) -> str:
    """소수점 숫자를 한국어 발화형으로 변환."""
    int_part = _int_to_korean(int(m.group(1)))
    frac_digits = "".join(_KO_UNITS[int(c)] for c in m.group(2))
    return f"{int_part} 점 {frac_digits}"


def _replace_money(m: re.Match) -> str:
    """천 단위 구분자가 있는 금액을 한국어 발화형으로 변환."""
    num = int(m.group(1).replace(",", ""))
    return f"{_int_to_korean(num)} 원"
