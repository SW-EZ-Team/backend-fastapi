"""부족 배열 보충(backfill)용 프롬프트 빌더와 응답 파서.

backfill.py(오케스트레이션)에서 프롬프트 문자열 구성과 응답 검증 책임을 분리한 모듈이다.
Modal guided_json 스키마(supporting_materials / voice_script)를 그대로 재사용하도록
extra에 schema_kind를 실어 보낸다. codex 경로에선 부족분이 없어 이 빌더가 호출되지 않는다.

공개 API:
    - build_quiz_backfill_request(lenient, missing, slide_count)
    - build_voice_backfill_request(lenient, slide_idx, slide_count)
    - parse_quiz_backfill(text) -> QuizBackfillResult
    - parse_voice_backfill(text) -> VoiceBackfillItem
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.pipeline.payload import (
    GeneratedQuiz,
    GeneratedSlide,
    LenientLessonPayload,
)
from common.llm_output import extract_json_block, strip_thinking

# 보충 호출 토큰 상한 — quiz 한 묶음 또는 voice 한 개를 받기에 충분한 여유값.
_QUIZ_MAX_TOKENS = 8000
_VOICE_MAX_TOKENS = 4000


class QuizBackfillResult(BaseModel):
    """supporting_materials 스키마 응답 — quizzes만 소비한다(assignment는 무시)."""

    model_config = ConfigDict(strict=True)

    quizzes: list[GeneratedQuiz] = Field(default_factory=list)


class VoiceBackfillItem(BaseModel):
    """voice_script 스키마 응답 — 단일 슬라이드 대본."""

    model_config = ConfigDict(strict=True)

    slide_idx: int = Field(ge=0, le=14)
    script_text: str = Field(min_length=40)


def build_quiz_backfill_request(
    lenient: LenientLessonPayload, missing: list[int], slide_count: int
) -> ChapterAIRequest:
    """빠진 slide_idx의 퀴즈를 supporting_materials 스키마로 재요청하는 요청을 만든다."""
    return ChapterAIRequest(
        system=_quiz_system(),
        user=_quiz_user(lenient, missing),
        max_tokens=_QUIZ_MAX_TOKENS,
        temperature=0.2,
        extra={"schema": "supporting_materials", "slide_count": slide_count, "lesson_backfill": True},
    )


def build_voice_backfill_request(
    lenient: LenientLessonPayload, slide_idx: int, slide_count: int
) -> ChapterAIRequest:
    """빠진 slide_idx의 음성대본을 voice_script 스키마로 재요청하는 요청을 만든다."""
    return ChapterAIRequest(
        system=_voice_system(),
        user=_voice_user(lenient, slide_idx),
        max_tokens=_VOICE_MAX_TOKENS,
        temperature=0.2,
        extra={"schema": "voice_script", "slide_count": slide_count, "slide_idx": slide_idx, "lesson_backfill": True},
    )


def parse_quiz_backfill(text: str) -> QuizBackfillResult:
    """supporting_materials 응답에서 quizzes 배열만 strict 검증해 꺼낸다."""
    block = extract_json_block(strip_thinking(text))
    return QuizBackfillResult.model_validate_json(block)


def parse_voice_backfill(text: str) -> VoiceBackfillItem:
    """voice_script 응답을 단일 대본 객체로 strict 검증해 꺼낸다."""
    block = extract_json_block(strip_thinking(text))
    return VoiceBackfillItem.model_validate_json(block)


def _quiz_system() -> str:
    return (
        "너는 ChapterStudio_V1의 누락 퀴즈 보충기다. 출력은 단일 JSON 객체 한 개뿐이며 "
        "최상위 키는 quizzes, assignment 두 개다. JSON 외 텍스트·사고과정·markdown fence·"
        "<think> 블록을 금지한다. quizzes[i]는 slide_idx, question, choices(보기 4개), "
        "answer_idx(0~3), difficulty, explanation 키를 갖는다. answer_idx는 정답 보기의 위치다. "
        "explanation은 정답 이유와 오답 함정을 함께 담는다. assignment는 형식 유지를 위한 최소값만 채운다."
    )


def _voice_system() -> str:
    return (
        "너는 ChapterStudio_V1의 누락 음성대본 보충기다. 출력은 단일 JSON 객체 한 개뿐이며 "
        "키는 slide_idx, script_text 두 개다. JSON 외 텍스트·사고과정·markdown fence·"
        "<think> 블록을 금지한다. script_text는 과외 선생님 말투의 자연스러운 존댓말 한 문단으로, "
        "화면 설명을 넘어선 깊은 풀이와 실수하기 쉬운 지점을 담는다. HTML 태그·markdown·글머리표를 넣지 않는다."
    )


def _quiz_user(lenient: LenientLessonPayload, missing: list[int]) -> str:
    lines = [
        f"다음 슬라이드들의 퀴즈가 빠져 있다. 이 slide_idx만 정확히 만들어라: {sorted(missing)}",
        "각 퀴즈는 해당 슬라이드 내용에서만 출제하며, 요청하지 않은 slide_idx는 절대 만들지 않는다.",
    ]
    for idx in sorted(missing):
        slide = _slide_by_idx(lenient, idx)
        if slide is not None:
            lines.append(f"- slide {idx}: 제목={slide.title} / 초점={slide.focus} / 점검={slide.checkpoint}")
    return "\n".join(lines)


def _voice_user(lenient: LenientLessonPayload, slide_idx: int) -> str:
    slide = _slide_by_idx(lenient, slide_idx)
    if slide is None:
        return f"slide_idx {slide_idx}의 음성대본을 만들어라."
    return (
        f"slide_idx {slide_idx}의 음성대본이 빠져 있다. 이 슬라이드만 대상으로 대본을 만든다.\n"
        f"제목={slide.title} / 초점={slide.focus} / 점검={slide.checkpoint}\n"
        f"반드시 slide_idx를 {slide_idx}로 고정한다."
    )


def _slide_by_idx(lenient: LenientLessonPayload, slide_idx: int) -> GeneratedSlide | None:
    for slide in lenient.slides:
        if slide.slide_idx == slide_idx:
            return slide
    return None


__all__ = [
    "QuizBackfillResult",
    "VoiceBackfillItem",
    "build_quiz_backfill_request",
    "build_voice_backfill_request",
    "parse_quiz_backfill",
    "parse_voice_backfill",
]
