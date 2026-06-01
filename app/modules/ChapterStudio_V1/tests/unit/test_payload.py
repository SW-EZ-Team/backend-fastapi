from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.payload import parse_payload
from app.modules.ChapterStudio_V1.pipeline.state_mapping import payload_to_state


@pytest.mark.parametrize("field", ["slides", "quizzes", "voice_scripts"])
def test_parse_payload_rejects_duplicate_slide_indices(field: str) -> None:
    payload = _payload(10)
    items = payload[field]
    assert isinstance(items, list)
    items.append(dict(items[0]))

    with pytest.raises(ConversionError):
        parse_payload(json.dumps(payload, ensure_ascii=False), 10)


def test_payload_to_state_preserves_assignment_metadata() -> None:
    payload = parse_payload(json.dumps(_payload(10), ensure_ascii=False), 10)

    state = payload_to_state(payload)

    assert state["assignment_meta"]["title"] == "실습"
    assert state["assignment_meta"]["assignment_format"] == "서술형"
    assert state["assignment_meta"]["expected_minutes"] == 20


def _payload(slide_count: int) -> dict[str, object]:
    return {
        "slides": [_slide(idx) for idx in range(slide_count)],
        "quizzes": [_quiz(idx) for idx in range(slide_count)],
        "note_blocks": [_note(idx) for idx in range(3)],
        "assignment": {
            "title": "실습",
            "assignment_format": "서술형",
            "expected_minutes": 20,
            "steps": ["핵심을 설명합니다."],
            "rubric": ["근거를 확인합니다."],
        },
        "voice_scripts": [
            {"slide_idx": idx, "script_text": "이번 슬라이드의 핵심 개념을 차분한 과외 말투로 풀어서 설명하는 음성 대본입니다."}
            for idx in range(slide_count)
        ],
    }


def _note(idx: int) -> dict[str, object]:
    return {
        "heading": f"핵심 {idx}",
        "bullets": ["핵심 개념을 다시 한 번 복습합니다.", "실수하기 쉬운 지점을 점검합니다."],
    }


def _slide(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "title": f"슬라이드 {idx}",
        "focus": "핵심",
        "checkpoint": "확인",
        "category": "text",
        "html": "<section><p>설명입니다.</p></section>",
        "css": "",
    }


def _quiz(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "question": "질문입니다.",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "이해",
        "explanation": "정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 함정입니다.",
    }
