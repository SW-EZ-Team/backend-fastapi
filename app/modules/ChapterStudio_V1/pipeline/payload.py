from __future__ import annotations

import json
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState, StateRecord, StateRecords
from app.modules.ChapterStudio_V1.schemas.response import Difficulty

SlideCategory = Literal["text", "diagram", "code", "math", "chart", "interactive", "table"]
_SlideIndexed = TypeVar("_SlideIndexed", bound="SlideIndexed")


class SlideIndexed(Protocol):
    slide_idx: int


class GeneratedSlide(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, le=14)
    title: str = Field(min_length=1)
    focus: str = Field(min_length=1)
    checkpoint: str = Field(min_length=1)
    category: SlideCategory
    html: str = Field(min_length=1)
    css: str = ""


class GeneratedQuiz(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, le=14)
    question: str = Field(min_length=1)
    choices: list[str] = Field(min_length=4, max_length=4)
    answer_idx: int = Field(ge=0, le=3)
    difficulty: Difficulty
    explanation: str = Field(min_length=1)


class GeneratedNoteBlock(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    heading: str = Field(min_length=1)
    bullets: list[str] = Field(min_length=1, max_length=6)


class GeneratedAssignment(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    title: str = Field(min_length=1)
    assignment_format: str = Field(min_length=1)
    expected_minutes: int = Field(ge=5, le=90)
    steps: list[str] = Field(min_length=1, max_length=8)
    rubric: list[str] = Field(min_length=1, max_length=8)


class GeneratedVoiceScript(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, le=14)
    script_text: str = Field(min_length=1)


class GeneratedLessonPayload(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slides: list[GeneratedSlide] = Field(min_length=10, max_length=15)
    quizzes: list[GeneratedQuiz] = Field(min_length=10, max_length=15)
    note_blocks: list[GeneratedNoteBlock] = Field(min_length=1, max_length=6)
    assignment: GeneratedAssignment
    voice_scripts: list[GeneratedVoiceScript] = Field(min_length=10, max_length=15)


def parse_payload(text: str, slide_count: int) -> GeneratedLessonPayload:
    """모델 응답에서 단일 JSON 객체를 꺼내 강의 산출물로 검증한다."""
    try:
        payload = GeneratedLessonPayload.model_validate_json(_extract_json_object(text))
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ConversionError(f"ChapterStudio JSON 검증 실패: {exc}") from exc
    _validate_indices(payload, slide_count)
    return payload


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


def _validate_indices(payload: GeneratedLessonPayload, slide_count: int) -> None:
    if not _has_exact_indices(payload.slides, slide_count):
        raise ConversionError("slides slide_idx가 요청 slide_count와 맞지 않는다.")
    if not _has_exact_indices(payload.quizzes, slide_count):
        raise ConversionError("quizzes slide_idx가 요청 slide_count와 맞지 않는다.")
    if not _has_exact_indices(payload.voice_scripts, slide_count):
        raise ConversionError("voice_scripts slide_idx가 요청 slide_count와 맞지 않는다.")


def _has_exact_indices(items: list[SlideIndexed], slide_count: int) -> bool:
    indices = [item.slide_idx for item in items]
    return len(indices) == slide_count and sorted(indices) == list(range(slide_count))


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        raise ValueError("JSON 객체 시작 문자가 없다.")
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            escaped = (char == "\\" and not escaped)
            if char == '"' and not escaped:
                in_string = False
            elif char != "\\":
                escaped = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    raise ValueError("JSON 객체가 닫히지 않았다.")


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


__all__ = ["GeneratedLessonPayload", "parse_payload", "payload_to_state"]
