"""LLM→TTS 플러시 정책 모듈.

순수 함수 — 외부 의존성 없이 텍스트 버퍼만 처리한다.
완결 문장을 추출하고 잔여 버퍼를 반환한다.
"""
from __future__ import annotations

import re

from app.modules.ASR_V1.pipeline.config import FLUSH_SECONDARY_MIN, FLUSH_SECONDARY_SCAN

# 1차 트리거: 문장 종결 패턴 — .?!。 또는 연속 줄바꿈
_SENTENCE_END_PATTERN: re.Pattern[str] = re.compile(r"[.?!。]|\n\n")


def extract_flushable(buffer: str) -> tuple[list[str], str]:
    """완전 문장을 추출하고 잔여 버퍼를 반환한다.

    Args:
        buffer: 누적된 전사 텍스트 버퍼

    Returns:
        (segments, remaining): 플러시할 문장 목록 + 잔여 텍스트
    """
    if not buffer:
        return [], ""

    segments: list[str] = []
    remaining = buffer

    # 1차 트리거: 문장 종결 부호 기준 분할
    primary_result = _extract_by_sentence_end(remaining)
    if primary_result:
        segments, remaining = primary_result
        return segments, remaining

    # 2차 트리거: 버퍼 길이 충족 + 끝 10자 내 쉼표 존재
    secondary_result = _extract_by_comma(remaining)
    if secondary_result:
        segments, remaining = secondary_result
        return segments, remaining

    return [], buffer


def _extract_by_sentence_end(text: str) -> tuple[list[str], str] | None:
    """문장 종결 부호로 완결 문장을 분할한다."""
    parts = _SENTENCE_END_PATTERN.split(text)
    # 패턴이 없으면 분할 불가
    if len(parts) <= 1:
        return None

    # 종결부호를 포함한 인덱스를 찾아 재조합
    segments: list[str] = []
    pos = 0
    for match in _SENTENCE_END_PATTERN.finditer(text):
        segment = text[pos : match.end()].strip()
        if segment:
            segments.append(segment)
        pos = match.end()

    remaining = text[pos:].strip()
    return segments, remaining


def _extract_by_comma(text: str) -> tuple[list[str], str] | None:
    """버퍼가 충분히 길고 끝 부분에 쉼표가 있으면 쉼표로 분할한다."""
    if len(text) < FLUSH_SECONDARY_MIN:
        return None

    # 끝 FLUSH_SECONDARY_SCAN 글자 내에 쉼표가 있는지 확인
    tail = text[-FLUSH_SECONDARY_SCAN:]
    comma_pos_in_tail = tail.rfind(",")
    if comma_pos_in_tail == -1:
        return None

    # 원문에서 실제 분할 위치 계산
    split_pos = len(text) - FLUSH_SECONDARY_SCAN + comma_pos_in_tail + 1
    segment = text[:split_pos].strip()
    remaining = text[split_pos:].strip()

    if not segment:
        return None

    return [segment], remaining
