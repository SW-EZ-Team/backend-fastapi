"""검증된 강의 payload → LangGraph 상태 조각 변환.

payload.py(파싱·검증 책임)에서 상태 변환 책임을 분리한 모듈이다. 입력은 항상 계약을
만족한 GeneratedLessonPayload(개수·slide_idx 완전집합 보장)이며, 여기서는 LLM을
호출하지 않는 순수 변환만 한다.

공개 API:
    - payload_to_state(payload) : slide/quiz/note/assignment/voice 상태 조각을 만든다.
"""
from __future__ import annotations

from typing import TypeVar

from app.modules.ChapterStudio_V1.pipeline.payload import (
    GeneratedAssignment,
    GeneratedLessonPayload,
    GeneratedNoteBlock,
    GeneratedQuiz,
    GeneratedSlide,
    GeneratedVoiceScript,
)
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState, StateRecord

_SlideIndexed = TypeVar("_SlideIndexed", GeneratedSlide, GeneratedQuiz, GeneratedVoiceScript)


def payload_to_state(payload: GeneratedLessonPayload) -> ChapterStudioState:
    """검증된 모델 JSON을 LangGraph 상태 조각으로 변환한다."""
    return {
        "slide_drafts": [_slide_record(slide) for slide in _sorted(payload.slides)],
        "quiz_set": [_quiz_record(quiz) for quiz in _sorted(payload.quizzes)],
        "core_note": _note_text(payload.note_blocks),
        "assignment_seed": _assignment_text(payload.assignment),
        "assignment_meta": _assignment_record(payload.assignment),
        "voice_scripts": [_voice_record(script) for script in _sorted(payload.voice_scripts)],
    }


def _sorted(items: list[_SlideIndexed]) -> list[_SlideIndexed]:
    return sorted(items, key=lambda item: item.slide_idx)


def _slide_record(slide: GeneratedSlide) -> StateRecord:
    return slide.model_dump()


def _quiz_record(quiz: GeneratedQuiz) -> StateRecord:
    data = quiz.model_dump()
    data["quiz_idx"] = quiz.slide_idx
    return data


def _voice_record(script: GeneratedVoiceScript) -> StateRecord:
    return script.model_dump()


def _assignment_record(item: GeneratedAssignment) -> StateRecord:
    return item.model_dump()


def _note_text(blocks: list[GeneratedNoteBlock]) -> str:
    sections: list[str] = []
    for block in blocks:
        bullets = "\n".join(f"- {bullet}" for bullet in block.bullets)
        sections.append(f"## {block.heading}\n{bullets}")
    return "\n\n".join(sections)


def _assignment_text(item: GeneratedAssignment) -> str:
    steps = "\n".join(f"{idx + 1}. {step}" for idx, step in enumerate(item.steps))
    rubric = "\n".join(f"- {row}" for row in item.rubric)
    return (
        f"{item.title}\n"
        f"형식: {item.assignment_format}\n"
        f"예상 시간: {item.expected_minutes}분\n\n"
        f"절차\n{steps}\n\n평가 기준\n{rubric}"
    )


__all__ = ["payload_to_state"]
