"""한국어 TTS 발화를 위한 텍스트 정규화 모듈.

보수적 원칙: TTS 발음이 명백히 깨지는 패턴만 변환.
코드·ID 등 비-한국어 문맥의 숫자는 건드리지 않는다.
"""
from __future__ import annotations

import re

from app.modules.TTS_V2.processors._ko_number_reader import (
    _int_to_korean,
    _replace_date,
    _replace_decimal,
    _replace_money,
    _replace_pct,
    _replace_phone,
    _replace_year,
)
from common.pronunciation import normalize_pronunciation_terms

# 영문 대문자 약어 패턴 (2~5글자)
_ABBR_RE = re.compile(r"\b([A-Z]{2,5})\b")
# 숫자 + 단위 패턴
_NUM_UNIT_RE = re.compile(
    r"(\d[\d,\.]*)\s*(km|m|cm|mm|kg|g|mg|℃|°C|°F|kHz|Hz|MHz|GB|MB|KB|dB|dBFS)"
)
# 소수점 숫자
_DECIMAL_RE = re.compile(r"\b(\d+)\.(\d+)\b")
# 퍼센트
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# 연도 (4자리 연도 + 년)
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\s*년")
# 전화번호 (010-XXXX-XXXX 등)
_PHONE_RE = re.compile(r"\b(0\d{1,2})-(\d{3,4})-(\d{4})\b")
# 날짜 (N월 N일)
_DATE_RE = re.compile(r"\b(\d{1,2})\s*월\s*(\d{1,2})\s*일")
# 금액 (숫자,숫자원 — 천 단위 구분자 있는 경우)
_MONEY_RE = re.compile(r"(\d{1,3}(?:,\d{3})+)\s*원")
# 연속 구두점 (느낌표·물음표)
_MULTI_EXCL_RE = re.compile(r"[!！]{2,}")
_MULTI_QUES_RE = re.compile(r"[?？]{2,}")
# 줄임표
_ELLIPSIS_RE = re.compile(r"\.{2,}|…")
# 짧은 괄호 내용 (10자 이하 제거)
_SHORT_PAREN_RE = re.compile(r"\(([^)]{1,10})\)")
_LONG_PAREN_RE = re.compile(r"\(([^)]{11,})\)")


# ── 단위 사전 ──────────────────────────────────────────
_UNITS: dict[str, str] = {
    "km": "킬로미터", "m": "미터", "cm": "센티미터", "mm": "밀리미터",
    "kg": "킬로그램", "g": "그램", "mg": "밀리그램",
    "℃": "섭씨", "°C": "섭씨", "°F": "화씨",
    "kHz": "킬로헤르츠", "Hz": "헤르츠", "MHz": "메가헤르츠",
    "GB": "기가바이트", "MB": "메가바이트", "KB": "킬로바이트",
    "dB": "데시벨", "dBFS": "디비에프에스",
}

# ── 약어 사전 ──────────────────────────────────────────
_ABBRS: dict[str, str] = {
    "AI": "에이아이", "API": "에이피아이", "URL": "유알엘",
    "HTML": "에이치티엠엘", "CSS": "씨에스에스", "JS": "제이에스",
    "PDF": "피디에프", "GPU": "지피유", "CPU": "씨피유",
    "TTS": "티티에스", "ASR": "에이에스알", "LLM": "엘엘엠",
    "CER": "씨이알", "WER": "더블유이알",
    "MPS": "엠피에스", "MLX": "엠엘엑스",
    "LUFS": "럽스", "RTF": "알티에프",
}

# 영문 알파벳 → 한국어 발음 (글자별 분리용)
_ALPHA_KO: dict[str, str] = {
    "A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이",
    "F": "에프", "G": "지", "H": "에이치", "I": "아이", "J": "제이",
    "K": "케이", "L": "엘", "M": "엠", "N": "엔", "O": "오",
    "P": "피", "Q": "큐", "R": "알", "S": "에스", "T": "티",
    "U": "유", "V": "브이", "W": "더블유", "X": "엑스",
    "Y": "와이", "Z": "지",
}

# 테스트 호환: _int_to_korean을 이 모듈 네임스페이스에서도 참조 가능하도록 유지
# (test_normalizer.py에서 from text_normalizer import _int_to_korean 사용 중)
__all__ = [
    "normalize_for_tts",
    "expand_numbers",
    "expand_units",
    "expand_abbreviations",
    "expand_symbols",
    "normalize_punctuation",
    "_int_to_korean",
]


def normalize_for_tts(text: str) -> str:
    """TTS 발화를 위한 한국어 텍스트 정규화 진입점."""
    text = expand_numbers(text)
    text = expand_units(text)
    text = expand_abbreviations(text)
    text = normalize_pronunciation_terms(text)
    text = expand_symbols(text)
    text = normalize_punctuation(text)
    return text


def expand_numbers(text: str) -> str:
    """한국어 문맥에 인접한 숫자를 한국어 발화형으로 변환.

    코드·ID처럼 한글이 없는 숫자는 변환하지 않는다.
    """
    # 전화번호: 010-1234-5678 → 공일공 일이삼사 오육칠팔
    text = _PHONE_RE.sub(_replace_phone, text)
    # 날짜: 4월 23일 → 사월 이십삼일
    text = _DATE_RE.sub(_replace_date, text)
    # 연도: 2024년 → 이천이십사 년
    text = _YEAR_RE.sub(_replace_year, text)
    # 퍼센트: 95% → 구십오 퍼센트
    text = _PCT_RE.sub(_replace_pct, text)
    # 소수점: 3.14 → 삼 점 일사 (한글 인접 시에만)
    text = _DECIMAL_RE.sub(_replace_decimal, text)
    # 금액: 10,000원 → 만 원
    text = _MONEY_RE.sub(_replace_money, text)
    return text


def expand_units(text: str) -> str:
    """숫자 + 단위 패턴에서만 단위를 한국어 발화형으로 치환."""
    def _repl(m: re.Match) -> str:
        num_part = m.group(1)
        unit_str = m.group(2)
        ko_unit = _UNITS.get(unit_str, unit_str)
        return f"{num_part} {ko_unit}"

    return _NUM_UNIT_RE.sub(_repl, text)


def expand_abbreviations(text: str) -> str:
    """영문 약어를 한국어 발화형으로 변환.

    사전에 없는 약어는 글자별로 분리해 발음한다.
    """
    def _repl(m: re.Match) -> str:
        abbr = m.group(1)
        if abbr in _ABBRS:
            return _ABBRS[abbr]
        # 사전 미등록 약어 → 글자별 한국어 발음 결합
        return "".join(_ALPHA_KO.get(ch, ch) for ch in abbr)

    return _ABBR_RE.sub(_repl, text)


def expand_symbols(text: str) -> str:
    """수식 문맥 기호를 한국어 발화형으로 변환.

    일반 문장의 '-'(빼기가 아닌 줄임표 등)는 건드리지 않는다.
    """
    # 화살표 계열 (수식 아닌 서술 기호)
    text = text.replace("→", "에서 로")
    text = text.replace("←", "에서 로")
    text = text.replace("↔", "양방향")
    text = text.replace("~", "에서")
    # 수학 연산자
    text = text.replace("×", "곱하기")
    text = text.replace("÷", "나누기")
    text = text.replace("≥", "이상")
    text = text.replace("≤", "이하")
    text = text.replace("±", "플러스 마이너스")
    text = text.replace("∞", "무한대")
    # 상용 기호
    text = text.replace("&", "앤드")
    text = text.replace("@", "앳")
    return text


def normalize_punctuation(text: str) -> str:
    """구두점을 TTS 발화에 적합하게 정리."""
    # 줄임표 단순화
    text = _ELLIPSIS_RE.sub(".", text)
    # 연속 느낌표·물음표 → 1개로
    text = _MULTI_EXCL_RE.sub("!", text)
    text = _MULTI_QUES_RE.sub("?", text)
    # 10자 이하 괄호 내용 제거 (발음에 어색)
    text = _SHORT_PAREN_RE.sub("", text)
    # 11자 이상 괄호는 괄호 기호만 제거하고 내용 유지
    text = _LONG_PAREN_RE.sub(r"\1", text)
    return text
