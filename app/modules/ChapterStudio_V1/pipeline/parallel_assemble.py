"""병렬 생성된 컴포넌트를 단일 강의 payload로 조립.

컴포넌트별로 따로 받은 slides/quizzes/note_blocks/assignment/voice_scripts를 하나의
LenientLessonPayload로 모은 뒤, finalize_payload로 최종 엄격 계약(개수·slide_idx 완전집합)을
강제한다. 계약이 깨지면 ConversionError로 드러낸다(빈 값으로 삼키지 않는다 — 다운스트림
persistence가 계약에 의존한다).

공개 API:
    - assemble_payload(bundle, slide_count) -> GeneratedLessonPayload
"""
from __future__ import annotations

from dataclasses import dataclass

from app.modules.ChapterStudio_V1.pipeline.payload import (
    GeneratedAssignment,
    GeneratedLessonPayload,
    GeneratedNoteBlock,
    GeneratedQuiz,
    GeneratedSlide,
    GeneratedVoiceScript,
    LenientLessonPayload,
    finalize_payload,
)


@dataclass(frozen=True)
class ComponentBundle:
    """병렬 생성된 컴포넌트 묶음(조립 전 원자료)."""

    slides: list[GeneratedSlide]
    quizzes: list[GeneratedQuiz]
    note_blocks: list[GeneratedNoteBlock]
    assignment: GeneratedAssignment
    voice_scripts: list[GeneratedVoiceScript]


def assemble_payload(bundle: ComponentBundle, slide_count: int) -> GeneratedLessonPayload:
    """컴포넌트 묶음을 LenientLessonPayload로 모아 최종 계약을 강제한 payload를 만든다."""
    lenient = LenientLessonPayload(
        slides=_sorted(bundle.slides),
        quizzes=_sorted(bundle.quizzes),
        note_blocks=bundle.note_blocks,
        assignment=bundle.assignment,
        voice_scripts=_sorted(bundle.voice_scripts),
    )
    # finalize_payload가 개수·slide_idx 0..n-1 완전집합 계약을 강제한다(미충족 시 ConversionError).
    return finalize_payload(lenient, slide_count)


def _sorted(items: list) -> list:
    """slide_idx 순으로 정렬한다(병렬 완료 순서에 의존하지 않게 한다)."""
    return sorted(items, key=lambda item: item.slide_idx)


__all__ = ["ComponentBundle", "assemble_payload"]
