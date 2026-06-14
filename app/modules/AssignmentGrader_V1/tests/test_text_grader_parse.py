"""text_grader JSON 파싱 회귀 테스트 (2026-06-14 라이브 채점 실패 수정).

reasoning 모델(gemini-3.5-flash)이 <think> 블록·서문을 흘려 JSON 중괄호가
가려지던 채점 실패를, strip_thinking 선처리로 복구하는지 검증한다.
"""
from __future__ import annotations

import pytest

from app.modules.AssignmentGrader_V1.text_grader import (
    TextGradingError,
    _parse_grading_json,
)


def test_parse_plain_json() -> None:
    res = _parse_grading_json('{"score": 80, "feedback": "좋아요", "ai_confidence": 0.8}')
    assert res.score == 80
    assert res.ai_confidence == pytest.approx(0.8)


def test_parse_thinking_wrapped_json() -> None:
    """<think>...</think> 뒤의 JSON을 정상 추출한다."""
    raw = (
        "<think>학생 답안의 BST 삽입·삭제가 정확하다. 92점 정도로 본다.</think>\n"
        '{"score": 92, "feedback": "삽입·삭제 과정이 정확합니다.", "ai_confidence": 0.9}'
    )
    res = _parse_grading_json(raw)
    assert res.score == 92
    assert "정확" in res.feedback


def test_parse_unclosed_think_then_json() -> None:
    """닫히지 않은 <think> 이후 텍스트는 절단되지만, 그 앞/별도 JSON이 있으면 추출한다."""
    raw = '{"score": 70, "feedback": "보완 필요", "ai_confidence": 0.6}\n<think>추가 사고...'
    res = _parse_grading_json(raw)
    assert res.score == 70


def test_parse_no_json_raises() -> None:
    """JSON 중괄호가 전혀 없으면 명확한 오류를 던진다(점수 0 침묵 출고 방지)."""
    with pytest.raises(TextGradingError):
        _parse_grading_json("죄송하지만 채점할 수 없습니다.")


def test_score_clamped() -> None:
    """범위를 벗어난 점수/확신도는 0~100, 0~1로 보정한다."""
    res = _parse_grading_json('{"score": 150, "feedback": "x", "ai_confidence": 2.0}')
    assert res.score == 100
    assert res.ai_confidence == pytest.approx(1.0)
