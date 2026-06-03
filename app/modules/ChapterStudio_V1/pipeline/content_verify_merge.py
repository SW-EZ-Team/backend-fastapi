"""내용 검증/교정 응답의 파싱·검증·병합.

검증 패스의 오류 목록과 교정 패스의 부분 산출물을 strict Pydantic으로 검증하고, 슬라이드
html·퀴즈 explanation·voice script_text만 교체해 새 payload를 만든다(슬라이드 인덱스·키
계약 불변). think 제거·JSON 추출은 공통 유틸(common.llm_output)을 쓴다.

공개 API:
    - parse_errors(text)                  : 검증 응답 → 오류 dict 목록(빈 목록 가능)
    - parse_correction(text)              : 교정 응답 → 검증된 _CorrectionResult
    - apply_corrections(payload, result)  : 교정을 병합한 새 payload
    - indices_intact(payload, slide_count): 슬라이드 인덱스 계약 보존 여부
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ChapterStudio_V1.pipeline.payload import (
    GeneratedLessonPayload,
    GeneratedVoiceScript,
)
from common.llm_output import extract_json_block, strip_thinking

# 슬라이드 인덱스 상한(payload 스키마의 le=14와 정합).
_MAX_SLIDE_IDX = 14


class _VerifyError(BaseModel):
    """검증 패스가 보고한 단일 오류 항목."""

    model_config = ConfigDict(strict=True)

    location: str = ""
    field: Literal["slide", "quiz", "voice"]
    slide_idx: int = Field(ge=0, le=_MAX_SLIDE_IDX)
    what_is_wrong: str = Field(min_length=1)
    correction: str = Field(min_length=1)


class _VerifyResult(BaseModel):
    model_config = ConfigDict(strict=True)

    errors: list[_VerifyError] = Field(default_factory=list)


class _SlideCorrection(BaseModel):
    model_config = ConfigDict(strict=True)

    slide_idx: int = Field(ge=0, le=_MAX_SLIDE_IDX)
    html: str = Field(min_length=1)


class _QuizCorrection(BaseModel):
    model_config = ConfigDict(strict=True)

    slide_idx: int = Field(ge=0, le=_MAX_SLIDE_IDX)
    explanation: str = Field(min_length=30)


class _VoiceCorrection(BaseModel):
    model_config = ConfigDict(strict=True)

    slide_idx: int = Field(ge=0, le=_MAX_SLIDE_IDX)
    script_text: str = Field(min_length=40)


class _CorrectionResult(BaseModel):
    """교정 응답 — 고친 항목만 부분적으로 담는다(없으면 빈 배열)."""

    model_config = ConfigDict(strict=True)

    slides: list[_SlideCorrection] = Field(default_factory=list)
    quiz_explanations: list[_QuizCorrection] = Field(default_factory=list)
    voice_scripts: list[_VoiceCorrection] = Field(default_factory=list)


def parse_errors(text: str) -> list[dict[str, object]]:
    """검증 응답을 strict 검증해 오류 dict 목록으로 돌려준다(없으면 빈 목록)."""
    block = extract_json_block(strip_thinking(text))
    result = _VerifyResult.model_validate_json(block)
    return [err.model_dump() for err in result.errors]


def parse_correction(text: str) -> _CorrectionResult:
    """교정 응답을 strict 검증된 부분 산출물로 돌려준다."""
    block = extract_json_block(strip_thinking(text))
    return _CorrectionResult.model_validate_json(block)


def combine_corrections(results: list[_CorrectionResult]) -> _CorrectionResult:
    """그룹별 병렬 교정 결과를 하나의 _CorrectionResult로 합친다(병렬 교정용).

    각 그룹 교정은 자기 그룹 키만 채우므로 단순 연결로 충돌 없이 합쳐진다. 같은 slide_idx가
    여러 결과에 중복돼도 apply_corrections가 마지막 값을 dict로 덮어 쓰므로 안전하다.
    """
    slides: list[_SlideCorrection] = []
    quiz_explanations: list[_QuizCorrection] = []
    voice_scripts: list[_VoiceCorrection] = []
    for result in results:
        slides.extend(result.slides)
        quiz_explanations.extend(result.quiz_explanations)
        voice_scripts.extend(result.voice_scripts)
    return _CorrectionResult(
        slides=slides, quiz_explanations=quiz_explanations, voice_scripts=voice_scripts
    )


def apply_corrections(
    payload: GeneratedLessonPayload, result: _CorrectionResult
) -> GeneratedLessonPayload:
    """교정 항목만 기존 payload에 병합한 새 payload를 만든다(인덱스·키 불변)."""
    slide_by_idx = {item.slide_idx: item.html for item in result.slides}
    expl_by_idx = {item.slide_idx: item.explanation for item in result.quiz_explanations}
    voice_by_idx = {item.slide_idx: item.script_text for item in result.voice_scripts}
    new_slides = [
        slide.model_copy(update={"html": slide_by_idx[slide.slide_idx]})
        if slide.slide_idx in slide_by_idx
        else slide
        for slide in payload.slides
    ]
    new_quizzes = [
        quiz.model_copy(update={"explanation": expl_by_idx[quiz.slide_idx]})
        if quiz.slide_idx in expl_by_idx
        else quiz
        for quiz in payload.quizzes
    ]
    new_voice = [
        # 교정 시 sections는 제거하고 script_text만 반영한다(교정기는 자유 텍스트 반환).
        GeneratedVoiceScript(
            slide_idx=script.slide_idx,
            script_text=voice_by_idx.get(script.slide_idx, script.script_text),
            sections=None if script.slide_idx in voice_by_idx else script.sections,
        )
        for script in payload.voice_scripts
    ]
    return payload.model_copy(
        update={"slides": new_slides, "quizzes": new_quizzes, "voice_scripts": new_voice}
    )


def indices_intact(payload: GeneratedLessonPayload, slide_count: int) -> bool:
    """슬라이드/퀴즈/voice의 slide_idx 집합이 0..slide_count-1과 정확히 일치하는지 본다."""
    expected = set(range(slide_count))
    slide_idx = {slide.slide_idx for slide in payload.slides}
    quiz_idx = {quiz.slide_idx for quiz in payload.quizzes}
    voice_idx = {script.slide_idx for script in payload.voice_scripts}
    return slide_idx == expected and quiz_idx == expected and voice_idx == expected


__all__ = [
    "apply_corrections",
    "combine_corrections",
    "indices_intact",
    "parse_correction",
    "parse_errors",
]
