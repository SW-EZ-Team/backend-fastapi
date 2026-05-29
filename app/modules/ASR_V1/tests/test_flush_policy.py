"""flush_policy 단위 테스트.

1차 트리거(문장 종결 부호), 2차 트리거(쉼표), 빈 입력, 잔여 버퍼를 검증한다.
"""
from __future__ import annotations

import pytest

from app.modules.ASR_V1.pipeline.flush_policy import extract_flushable


def test_empty_buffer_returns_empty() -> None:
    """빈 문자열은 빈 세그먼트와 빈 잔여를 반환한다."""
    segments, remaining = extract_flushable("")
    assert segments == []
    assert remaining == ""


def test_no_trigger_returns_buffer_unchanged() -> None:
    """종결 부호/쉼표 없는 짧은 텍스트는 변환 없이 반환된다."""
    text = "안녕하세요"
    segments, remaining = extract_flushable(text)
    assert segments == []
    assert remaining == text


def test_period_trigger() -> None:
    """마침표로 완결 문장이 추출된다."""
    text = "안녕하세요. 반갑습니다"
    segments, remaining = extract_flushable(text)
    assert len(segments) >= 1
    assert "안녕하세요." in segments[0]
    assert "반갑습니다" in remaining


def test_question_mark_trigger() -> None:
    """물음표로 완결 문장이 추출된다."""
    text = "오늘 날씨가 어때요? 좋네요"
    segments, remaining = extract_flushable(text)
    assert len(segments) >= 1
    assert remaining.strip() != ""


def test_exclamation_trigger() -> None:
    """느낌표로 완결 문장이 추출된다."""
    text = "정말 대단해요! 계속 해주세요"
    segments, remaining = extract_flushable(text)
    assert len(segments) >= 1


def test_double_newline_trigger() -> None:
    """이중 줄바꿈으로 완결 문장이 추출된다."""
    text = "첫 번째 문단입니다\n\n두 번째 문단"
    segments, remaining = extract_flushable(text)
    assert len(segments) >= 1


def test_secondary_comma_trigger() -> None:
    """버퍼가 30자 이상이고 끝 10자 내 쉼표가 있으면 추출된다."""
    # 30자 이상 텍스트에 쉼표 삽입
    text = "이것은 매우 긴 문장으로 30자 이상이 되어야 합니다,"
    assert len(text) >= 30
    segments, remaining = extract_flushable(text)
    assert len(segments) >= 1


def test_secondary_no_trigger_short_buffer() -> None:
    """30자 미만 버퍼는 2차 트리거가 작동하지 않는다."""
    text = "짧은 텍스트,"
    assert len(text) < 30
    segments, remaining = extract_flushable(text)
    assert segments == []


def test_multiple_sentences() -> None:
    """여러 종결 부호가 있으면 모두 추출된다."""
    text = "첫 문장입니다. 두 번째 문장입니다. 세 번째"
    segments, remaining = extract_flushable(text)
    assert len(segments) >= 2
    assert "세 번째" in remaining
