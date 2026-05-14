from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.ChapterStudio_V1.schemas.response import (
    AssignmentSchema,
    ChapterResponse,
    NoteSchema,
    QuizSchema,
    SlideSchema,
    VoiceScriptSchema,
)


def test_chapter_response_happy_path() -> None:
    response = ChapterResponse(
        chapter_id="ch1",
        slides=[SlideSchema(chapter_id="ch1", slide_idx=0, html_content="<section>1</section>")],
        quizzes=[
            QuizSchema(
                chapter_id="ch1",
                quiz_idx=0,
                question="질문",
                choices=["A", "B", "C", "D"],
                answer_idx=0,
                difficulty="이해",
            )
        ],
        note=NoteSchema(chapter_id="ch1", content="노트"),
        assignment=AssignmentSchema(chapter_id="ch1", content="과제"),
        voice_scripts=[
            VoiceScriptSchema(
                chapter_id="ch1",
                slide_idx=0,
                script_text="대본",
                audio_url="mock://audio/a",
                duration_hint_sec=1.2,
            )
        ],
    )

    assert response.chapter_id == "ch1"
    assert response.voice_scripts[0].audio_url == "mock://audio/a"


def test_quiz_choices_must_be_four() -> None:
    with pytest.raises(ValidationError):
        QuizSchema(
            chapter_id="ch1",
            quiz_idx=0,
            question="질문",
            choices=["A", "B", "C"],
            answer_idx=0,
            difficulty="이해",
        )


def test_slide_idx_must_be_non_negative() -> None:
    with pytest.raises(ValidationError):
        SlideSchema(chapter_id="ch1", slide_idx=-1, html_content="<section>1</section>")
