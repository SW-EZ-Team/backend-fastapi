"""교정 diff 생성 + 할루시네이션 판정 아톰.

Kanana 모델 출력의 '머리말 한 줄 추가', '부가 설명 추가' 잔여 패턴을
사후 정리(trim)하고, raw ↔ corrected 를 SequenceMatcher 로 diff 처리해
Correction 리스트를 만든다. 할루시네이션 판정은 probe 스크립트와 동일한
길이 휴리스틱을 사용한다.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..schemas import Correction

# probe 검증: Kanana 는 간혹 "[교정 결과]" 같은 머리말을 붙인다.
# 이런 메타 토큰을 앞쪽에서만 제거한다.
_META_HEAD_PATTERNS: tuple[str, ...] = (
    r"^\s*\[?\s*교정\s*결과\s*\]?\s*[:\-]?\s*",
    r"^\s*교정본\s*[:\-]?\s*",
    r"^\s*교정\s*[:\-]?\s*",
    r"^\s*Answer\s*[:\-]?\s*",
)

# 끝에 붙는 설명구(Kanana 가 드물게 "이상입니다." 류를 붙임) 제거
_META_TAIL_PATTERNS: tuple[str, ...] = (
    r"\s*이상입니다\.?\s*$",
    r"\s*끝\.?\s*$",
)


def trim_model_output(raw_output: str) -> str:
    """Kanana 응답에서 메타 머리말·꼬리말을 잘라낸 순수 교정 텍스트 반환."""
    text = raw_output.strip()
    for pat in _META_HEAD_PATTERNS:
        text = re.sub(pat, "", text, count=1)
    for pat in _META_TAIL_PATTERNS:
        text = re.sub(pat, "", text, count=1)
    return text.strip()


def diff_corrections(raw: str, corrected: str) -> list[Correction]:
    """원문 ↔ 교정본을 SequenceMatcher 로 비교해 Correction 리스트 생성.

    변경이 있는 (replace/delete/insert) 블록만 Correction 으로 기록하고,
    equal 블록은 건너뛴다. reason 은 간단한 경험적 태그 규칙으로 부여한다.
    (typo: 길이 유사 & 한글 치환, spacing: 공백 증감 위주, reconstructed: 그 외)
    """
    if not raw:
        return []
    sm = SequenceMatcher(a=raw, b=corrected, autojunk=False)
    corrections: list[Correction] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        original_fragment = raw[i1:i2]
        corrected_fragment = corrected[j1:j2]
        if not original_fragment and not corrected_fragment:
            continue
        reason = _classify_change(original_fragment, corrected_fragment)
        corrections.append(
            Correction(
                original=original_fragment,
                corrected=corrected_fragment,
                reason=reason,
            ),
        )
    return corrections


def _classify_change(original: str, corrected: str) -> str:
    """변경 블록을 간단한 경험 규칙으로 분류한다."""
    # 공백만 증감 — 띄어쓰기 교정
    if original.replace(" ", "") == corrected.replace(" ", ""):
        return "spacing"
    # 원문/교정본 한쪽이 비어있으면 insert/delete 로 분류
    if not original:
        return "insert"
    if not corrected:
        return "delete"
    # 길이가 비슷하고 한글이 섞여있으면 오타 교정 가능성이 높다
    if abs(len(original) - len(corrected)) <= 2 and _has_korean(original + corrected):
        return "typo"
    # 나머지는 폭넓게 '재구성' 으로 표기
    return "reconstructed"


def _has_korean(text: str) -> bool:
    """한글 포함 여부 판정 — AC00~D7A3 범위만 본다."""
    return any("\uac00" <= ch <= "\ud7a3" for ch in text)


def detect_hallucination(raw: str, corrected: str) -> bool:
    """probe 스크립트와 동일한 길이 휴리스틱.

    결과 길이가 원문 대비 20%+ 증가하면 의심. VLM 반복구가 원문에 섞여 있던
    케이스에서는 '반복구 제거' 때문에 corrected 가 훨씬 짧으므로 이 규칙은
    통과한다 (증가가 아닌 감소는 판정에서 제외).
    """
    # raw 가 비어 있는 병적 케이스에서는 판정을 유예(False)
    if not raw:
        return False
    # probe 코드와 동일: corrected > raw*1.2 일 때 의심
    return len(corrected) > len(raw) * 1.2
