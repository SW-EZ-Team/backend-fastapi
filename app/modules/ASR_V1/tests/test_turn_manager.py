"""TurnManager 단위 테스트.

음성→침묵 전이, 충분한 침묵 후 커밋, grace 대기, 리셋 동작을 검증한다.
"""
from __future__ import annotations

import pytest

from app.modules.ASR_V1.pipeline.turn_manager import TurnDecision, TurnManager


@pytest.fixture
def tm() -> TurnManager:
    """테스트용 TurnManager — 짧은 파라미터로 빠른 커밋 유도."""
    return TurnManager(min_silence_ms=500, turn_min_chars=2, grace_ms=100)


def test_no_commit_during_speech(tm: TurnManager) -> None:
    """발화 중에는 커밋이 발생하지 않는다."""
    decision = tm.update(is_speech=True, timestamp_ms=0.0, partial_text="안녕")
    assert decision["commit"] is False


def test_no_commit_short_silence(tm: TurnManager) -> None:
    """침묵이 짧으면 커밋이 발생하지 않는다."""
    tm.update(is_speech=True, timestamp_ms=0.0, partial_text="안녕")
    decision = tm.update(is_speech=False, timestamp_ms=100.0, partial_text="안녕")
    assert decision["commit"] is False


def test_commit_after_sufficient_silence(tm: TurnManager) -> None:
    """충분한 침묵(min + grace) 후 커밋이 발생한다."""
    tm.update(is_speech=True, timestamp_ms=0.0, partial_text="안녕하세요")
    tm.update(is_speech=False, timestamp_ms=100.0, partial_text="안녕하세요")
    # min_silence_ms(500) + grace_ms(100) = 600ms 이후
    decision = tm.update(is_speech=False, timestamp_ms=700.0, partial_text="안녕하세요")
    assert decision["commit"] is True


def test_no_commit_insufficient_chars(tm: TurnManager) -> None:
    """글자수가 부족하면 침묵이 충분해도 커밋되지 않는다."""
    tm.update(is_speech=True, timestamp_ms=0.0, partial_text="아")
    tm.update(is_speech=False, timestamp_ms=100.0, partial_text="아")
    decision = tm.update(is_speech=False, timestamp_ms=700.0, partial_text="아")
    assert decision["commit"] is False


def test_reset_clears_state(tm: TurnManager) -> None:
    """reset 후 상태가 초기화되어 커밋이 발생하지 않는다."""
    tm.update(is_speech=True, timestamp_ms=0.0, partial_text="안녕하세요")
    tm.update(is_speech=False, timestamp_ms=100.0, partial_text="안녕하세요")
    tm.reset()
    decision = tm.update(is_speech=False, timestamp_ms=700.0, partial_text="안녕하세요")
    assert decision["commit"] is False


def test_silence_duration_in_decision(tm: TurnManager) -> None:
    """TurnDecision에 silence_duration_ms가 포함된다."""
    tm.update(is_speech=True, timestamp_ms=0.0, partial_text="안녕")
    tm.update(is_speech=False, timestamp_ms=0.0, partial_text="안녕")
    decision = tm.update(is_speech=False, timestamp_ms=200.0, partial_text="안녕")
    assert decision["silence_duration_ms"] == pytest.approx(200.0)
