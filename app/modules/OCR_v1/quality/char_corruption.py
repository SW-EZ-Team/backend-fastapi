"""문자 오염률 측정 — 한국어 텍스트에서 깨진 문자 비율을 계산한다.

스캔 PDF 를 잘못된 코드페이지로 OCR 하면 한글이 CJK 한자나 특수문자로 둔갑하는
현상이 발생한다. 이 함수는 그 비율을 측정해 품질 게이트 판단에 사용한다.
"""
from __future__ import annotations

import re
import unicodedata

from .. import config as cfg

# 정상 한글 유니코드 범위
_HANGUL_SYLLABLES = re.compile(r"[가-힯]")
_HANGUL_JAMO = re.compile(r"[ᄀ-ᇿ]")
_HANGUL_COMPAT = re.compile(r"[㄰-㆏]")

# 한국어 문서에서 한글 대신 나타날 가능성이 높은 CJK 통합 한자 범위
# (한국어 문서에 중국어 한자가 실제로 포함된 경우를 구분하지 않으므로
#  이 지표는 '의심 비율'로 사용한다)
_CJK_UNIFIED = re.compile(r"[一-鿿]")


def _count_hangul(text: str) -> int:
    """정상 한글 문자 수를 반환한다."""
    return (
        len(_HANGUL_SYLLABLES.findall(text))
        + len(_HANGUL_JAMO.findall(text))
        + len(_HANGUL_COMPAT.findall(text))
    )


def _count_suspicious_cjk(text: str) -> int:
    """CJK 통합 한자 수를 반환한다 (오염 의심 지표)."""
    return len(_CJK_UNIFIED.findall(text))


def score_char_corruption(text: str) -> tuple[float, str]:
    """텍스트의 문자 오염률과 이유를 반환한다.

    반환: (corruption_ratio 0.0~1.0, reason 문자열)
    corruption_ratio 가 낮을수록 오염이 없음을 의미한다.
    """
    if not text.strip():
        # 텍스트가 비었으면 분류 불가 — 오염으로 간주하지 않고 0.0 반환
        return 0.0, "empty"

    # 알파벳·숫자·공백·구두점 등 기본 ASCII 를 제외한 비-ASCII 문자만 대상
    non_ascii = [c for c in text if ord(c) > 127]
    if not non_ascii:
        return 0.0, "ascii_only"

    hangul_count = _count_hangul(text)
    cjk_count = _count_suspicious_cjk(text)
    total_non_ascii = len(non_ascii)

    # 한글이 하나도 없고 CJK 가 다수인 경우 — 높은 오염 신호
    if hangul_count == 0 and cjk_count > 10:
        ratio = min(cjk_count / total_non_ascii, 1.0)
        return round(ratio, 4), "no_hangul_cjk_dominant"

    # 정상 케이스: CJK 대비 한글 비율로 오염률 역산
    if hangul_count + cjk_count == 0:
        return 0.0, "no_cjk_no_hangul"

    corruption = cjk_count / (hangul_count + cjk_count)
    reason = "ok" if corruption < cfg.char_corruption_max() else "high_cjk_ratio"
    return round(corruption, 4), reason
