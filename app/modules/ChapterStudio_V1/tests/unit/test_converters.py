from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.converters import request_to_initial_state, state_to_db_rows, state_to_response
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState
from app.modules.ChapterStudio_V1.schemas.request import ChapterRequest


def _state() -> ChapterStudioState:
    return {
        "user_id": "u1",
        "curriculum_id": "c1",
        "chapter_brief": "정렬 알고리즘",
        "enriched_brief": "보강 개요",
        "weak_points": "재귀",
        "slide_outline": [{"title": "도입"}],
        "slides": [{"slide_idx": 0, "html_content": "<section>1</section>"}],
        "quiz_set": [
            {
                "slide_idx": 0,
                "question": "질문",
                "choices": ["A", "B", "C", "D"],
                "answer_idx": 0,
                "difficulty": "이해",
            }
        ],
        "core_note": "핵심 노트",
        "assignment_seed": "과제",
        "voice_scripts": [{"slide_idx": 0, "script_text": "대본"}],
        "voice_audio_files": [{"slide_idx": 0, "audio_url": "mock://audio/a", "duration_hint_sec": 1.2}],
    }


def test_request_to_initial_state() -> None:
    req = ChapterRequest(user_id="u1", curriculum_id="c1", chapter_brief="정렬", slide_count=10)

    state = request_to_initial_state(req)

    assert state["user_id"] == "u1"
    assert state["slides"] == []


def test_state_to_response_happy_path() -> None:
    response = state_to_response(_state(), "ch1")

    assert response.slides[0].html_content == "<section>1</section>"
    assert response.quizzes[0].quiz_idx == 0
    assert response.quizzes[0].choices == ["A", "B", "C", "D"]
    assert response.voice_scripts[0].audio_url == "mock://audio/a"
    assert response.voice_scripts[0].duration_hint_sec == 1.2


def test_state_to_db_rows_happy_path() -> None:
    rows = state_to_db_rows(_state(), "ch1")

    assert set(rows) == {"slide", "quiz", "note", "assignment", "voice_script"}
    assert rows["note"][0]["chapter_id"] == "ch1"
    assert rows["voice_script"][0]["audio_url"] == "mock://audio/a"
    assert rows["voice_script"][0]["duration_hint_sec"] == 1.2


def test_state_to_response_keeps_legacy_quiz_idx() -> None:
    state = _state()
    state["quiz_set"][0]["quiz_idx"] = 7

    response = state_to_response(state, "ch1")

    assert response.quizzes[0].quiz_idx == 7


def test_state_to_response_rejects_missing_slide_list() -> None:
    state = _state()
    del state["slides"]

    with pytest.raises(ConversionError):
        state_to_response(state, "ch1")


def test_state_to_response_rejects_bad_difficulty() -> None:
    state = _state()
    state["quiz_set"][0]["difficulty"] = "unknown"

    with pytest.raises(ConversionError):
        state_to_response(state, "ch1")
