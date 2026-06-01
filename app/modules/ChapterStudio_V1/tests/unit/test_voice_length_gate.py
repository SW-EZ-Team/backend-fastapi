"""voice_length_gate 결정적 길이 게이트 순수 함수 검증.

LLM을 호출하지 않고 len() 기준으로 미달 항목을 찾는 기능을 확인한다:
    - min_chars 미만 → 오류 dict 반환(field="voice", slide_idx 일치).
    - min_chars 이상 → 빈 목록(no-op).
    - 부분 미달(일부만 짧음) → 미달 항목만 포함.
    - 오류 dict 형태가 content_verify_merge._VerifyError 계약과 호환되는지.
"""
from __future__ import annotations

import json

from app.modules.ChapterStudio_V1.pipeline.payload import parse_payload
from app.modules.ChapterStudio_V1.pipeline.voice_length_gate import (
    length_gate_errors,
    short_voice_indices,
    voice_extend_user_prompt,
)

_SLIDE_COUNT = 10  # GeneratedLessonPayload.slides 최소값(min_length=10)을 만족해야 한다.
_MIN_CHARS = 900


def test_all_short_voices_flagged() -> None:
    payload = _payload(voice_chars=600)

    errors = length_gate_errors(payload, _MIN_CHARS)

    assert len(errors) == _SLIDE_COUNT
    for err in errors:
        assert err["field"] == "voice"
        assert isinstance(err["slide_idx"], int)
        # what_is_wrong은 실제 길이와 기준을 포함해야 한다(디버깅 가시성).
        assert "600" in str(err["what_is_wrong"]) or str(err["slide_idx"]) in str(err["location"])
        assert "900" in str(err["correction"])


def test_all_long_voices_pass_gate() -> None:
    payload = _payload(voice_chars=950)

    errors = length_gate_errors(payload, _MIN_CHARS)

    assert errors == []


def test_partial_short_voices_flagged_only() -> None:
    # slide 1,3만 짧고 나머지는 충분한 케이스.
    payload = _payload_mixed(short_indices={1, 3}, voice_chars=600, long_chars=950)

    errors = length_gate_errors(payload, _MIN_CHARS)
    flagged = {int(e["slide_idx"]) for e in errors}

    assert flagged == {1, 3}
    assert all(e["field"] == "voice" for e in errors)


def test_short_voice_indices_matches_gate_errors() -> None:
    payload = _payload_mixed(short_indices={0, 2, 4}, voice_chars=600, long_chars=950)

    indices = short_voice_indices(payload, _MIN_CHARS)

    assert set(indices) == {0, 2, 4}


def test_voice_extend_prompt_references_current_draft() -> None:
    payload = _payload(voice_chars=600)
    short_idx = [0, 1]

    prompt = voice_extend_user_prompt(payload, short_idx, _MIN_CHARS)

    # 프롬프트에 기존 초안이 인용돼 있어야 한다(모델이 내용을 버리지 않게 안내).
    assert "slide 0" in prompt
    assert "slide 1" in prompt
    assert "900" in prompt
    # 확장 지시에 축소(줄이기) 금지 언급.
    assert "줄이거나" in prompt or "축소" in prompt


def test_gate_error_dict_compatible_with_verify_error_schema() -> None:
    """오류 dict가 _VerifyError 필드 계약(location/field/slide_idx/what_is_wrong/correction)과 호환."""
    payload = _payload(voice_chars=600)

    errors = length_gate_errors(payload, _MIN_CHARS)

    required_keys = {"location", "field", "slide_idx", "what_is_wrong", "correction"}
    for err in errors:
        assert required_keys.issubset(err.keys()), f"필수 키 누락: {required_keys - err.keys()}"
        # field는 반드시 "voice"여야 _affected_groups가 "voice" 그룹을 고른다.
        assert err["field"] == "voice"
        assert isinstance(err["slide_idx"], int)
        assert 0 <= int(err["slide_idx"]) <= 14


# ── 합성 payload 빌더 ────────────────────────────────────────────────


def _payload(voice_chars: int):
    return parse_payload(
        json.dumps(_dict(voice_chars=voice_chars, short_set=set(range(_SLIDE_COUNT))), ensure_ascii=False),
        _SLIDE_COUNT,
    )


def _payload_mixed(short_indices: set[int], voice_chars: int, long_chars: int):
    raw = {
        "slides": [_slide(i) for i in range(_SLIDE_COUNT)],
        "quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)],
        "note_blocks": [_note(i) for i in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [
            {
                "slide_idx": i,
                "script_text": "가" * (voice_chars if i in short_indices else long_chars),
            }
            for i in range(_SLIDE_COUNT)
        ],
    }
    return parse_payload(json.dumps(raw, ensure_ascii=False), _SLIDE_COUNT)


def _dict(voice_chars: int, short_set: set[int]) -> dict:
    return {
        "slides": [_slide(i) for i in range(_SLIDE_COUNT)],
        "quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)],
        "note_blocks": [_note(i) for i in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [
            {"slide_idx": i, "script_text": "가" * (voice_chars if i in short_set else 950)}
            for i in range(_SLIDE_COUNT)
        ],
    }


def _slide(idx: int) -> dict:
    return {
        "slide_idx": idx,
        "title": f"슬라이드 {idx}",
        "focus": "핵심",
        "checkpoint": "점검",
        "category": "text",
        "html": "<section><p>핵심 개념을 차근차근 설명합니다. 기초부터 쌓아가며 이해해 봅시다.</p></section>",
        "css": "",
    }


def _quiz(idx: int) -> dict:
    return {
        "slide_idx": idx,
        "question": "질문입니다.",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "이해",
        "explanation": "정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다.",
    }


def _note(idx: int) -> dict:
    return {
        "heading": f"핵심 {idx}",
        "bullets": [
            "핵심 개념을 한 문장으로 다시 정리하면서 배경까지 복습합니다.",
            "실수하기 쉬운 경계 조건을 직접 예시로 점검합니다.",
            "오해하기 쉬운 부분을 반례와 함께 짚습니다.",
        ],
    }


def _assignment() -> dict:
    return {
        "title": "실습 과제",
        "assignment_format": "문제풀이",
        "expected_minutes": 25,
        "steps": ["개념을 적용합니다.", "결과를 정리합니다."],
        "rubric": ["근거가 명확한가", "예외 처리가 정확한가"],
    }
