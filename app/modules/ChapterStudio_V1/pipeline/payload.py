from __future__ import annotations

import json
from typing import Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.normalize import normalize_lesson_dict
from app.modules.ChapterStudio_V1.schemas.response import Difficulty
from common.llm_output import extract_json_block, loads_lenient, strip_thinking

SlideCategory = Literal["text", "diagram", "code", "math", "chart", "interactive", "table"]

# 섹션 role 완전집합 — 결정적 순서 고정(AI가 변경 불가).
VOICE_SECTION_ROLES: tuple[str, ...] = ("intro", "core", "example", "closing")
VoiceSectionRole = Literal["intro", "core", "example", "closing"]


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
    narration: str = ""
    visual: dict[str, object] = Field(default_factory=dict)


class GeneratedQuiz(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, le=14)
    question: str = Field(min_length=1)
    choices: list[str] = Field(min_length=4, max_length=4)
    answer_idx: int = Field(ge=0, le=3)
    difficulty: Difficulty
    # 해설 하한을 보수적으로 둔다(품질 하한 30자). 본격 목표(120~180자)는 self-check+repair가 채운다.
    explanation: str = Field(min_length=30)


class GeneratedNoteBlock(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    heading: str = Field(min_length=1)
    # bullets 개수를 Modal guided_json(정확히 3개)과 정합화하되, 회귀 방지를 위해 2~4로 보수적으로 허용한다.
    bullets: list[str] = Field(min_length=2, max_length=4)


class GeneratedAssignment(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    title: str = Field(min_length=1)
    assignment_format: str = Field(min_length=1)
    expected_minutes: int = Field(ge=5, le=90)
    steps: list[str] = Field(min_length=1, max_length=8)
    rubric: list[str] = Field(min_length=1, max_length=8)


class VoiceSection(BaseModel):
    """음성대본 단일 섹션 슬롯 — role·text 두 키만 가진다."""

    model_config = ConfigDict(strict=True, frozen=True)

    role: VoiceSectionRole
    # 섹션별 최소 하한(가장 짧은 closing 기준). 실제 범위는 config 상수로 강제한다.
    text: str = Field(min_length=10)

    @field_validator("text")
    @classmethod
    def _strip_and_check(cls, value: str) -> str:
        """strip 후 길이로 판정해 전공백 텍스트가 통과하지 않게 한다.

        공백 10자가 min_length=10을 통과하면 sections≠script_text 불일치가 생기므로,
        실제 내용 길이로 검증하고 정규화한 값을 저장한다.
        """
        stripped = value.strip()
        if len(stripped) < 10:
            raise ValueError("섹션 text는 공백을 제외하고 최소 10자여야 한다.")
        return stripped


def _section_text(sec: object) -> str:
    """VoiceSection 인스턴스 또는 dict에서 strip된 text를 안전하게 꺼낸다."""
    if isinstance(sec, VoiceSection):
        return sec.text.strip()
    if isinstance(sec, dict):
        text = sec.get("text", "")
        if isinstance(text, str):
            return text.strip()
    return ""


def _join_sections(sections: list) -> str:
    """섹션 목록을 TTS 파이프라인이 소비하는 script_text로 결합한다(결정적 정책).

    VoiceSection 인스턴스와 raw dict 모두를 받아 strip된 text를 공백 1개로 잇는다.
    빈 섹션은 건너뛴다. 이 함수가 sections→script_text 파생의 단일 진실 소스다.
    """
    parts = [t for sec in sections if (t := _section_text(sec))]
    return " ".join(parts)


class GeneratedVoiceScript(BaseModel):
    """음성대본 스키마 — plan-first 섹션 슬롯과 TTS 호환 script_text를 함께 관리한다.

    하위호환 보장:
    - sections 없이 script_text만 오는 레거시 입력도 파싱 가능(Optional + 폴백).
    - script_text는 sections join 파생값으로 항상 유효하게 유지한다.
      다운스트림 TTS·DB·소비자는 script_text만 읽으면 기존과 동일하게 동작한다.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, le=14)
    # 음성대본 하한을 보수적으로 둔다(40자). 본격 목표(900~1600자)는 self-check+repair가 채운다.
    # TTS 파이프라인·DB·다운스트림이 소비하는 정본 필드 — 의미를 절대 바꾸지 않는다.
    script_text: str = Field(min_length=40)
    # plan-first 섹션 슬롯 — 4개 고정(intro/core/example/closing). 레거시 경로는 None.
    sections: list[VoiceSection] | None = None

    @model_validator(mode="before")
    @classmethod
    def _derive_script_text(cls, data: object) -> object:
        """sections가 있으면 script_text를 join 파생값으로 덮어쓴다.

        레거시 입력(script_text만): sections=None → script_text 그대로 보존.
        신규 입력(sections 있음): script_text를 sections join으로 파생해 항상 최신 유지.
        """
        if not isinstance(data, dict):
            return data
        sections_raw = data.get("sections")
        if not sections_raw:
            # 레거시 경로: script_text만 있으면 그대로 통과.
            return data
        # sections join 파생값으로 script_text를 결정적으로 덮어쓴다(_join_sections 단일 소스).
        derived = _join_sections(sections_raw)
        if derived:
            data = {**data, "script_text": derived}
        return data


class GeneratedLessonPayload(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slides: list[GeneratedSlide] = Field(min_length=10, max_length=15)
    quizzes: list[GeneratedQuiz] = Field(min_length=10, max_length=15)
    # note_blocks 개수를 Modal guided_json(정확히 4개)과 정합화하되, 회귀 방지를 위해 3~5로 보수적으로 허용한다.
    note_blocks: list[GeneratedNoteBlock] = Field(min_length=3, max_length=5)
    assignment: GeneratedAssignment
    voice_scripts: list[GeneratedVoiceScript] = Field(min_length=10, max_length=15)


class LenientLessonPayload(BaseModel):
    """1차 관대 파싱용 모델.

    각 항목의 구조·타입은 strict하게 검증하되(잘못된 quiz/voice는 여전히 거른다),
    배열 개수 하한과 slide_idx 완전집합 계약은 이 단계에서 강제하지 않는다. Qwen이
    뒤쪽 배열(quizzes/voice_scripts)을 slide_count보다 적게 생성하는 실측 케이스를
    hard-fail 대신 backfill로 보충하기 위함이다. 최종 계약은 finalize_payload가 강제한다.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    # 개수 하한 없음(부족 허용). 상한은 다운스트림 폭주 방어를 위해 유지한다.
    slides: list[GeneratedSlide] = Field(min_length=1, max_length=15)
    quizzes: list[GeneratedQuiz] = Field(max_length=15)
    note_blocks: list[GeneratedNoteBlock] = Field(min_length=3, max_length=5)
    assignment: GeneratedAssignment
    voice_scripts: list[GeneratedVoiceScript] = Field(max_length=15)


def parse_payload(text: str, slide_count: int) -> GeneratedLessonPayload:
    """모델 응답에서 단일 JSON 객체를 꺼내 강의 산출물로 검증한다(엄격, 계약 완전 강제).

    codex처럼 개수·인덱스 계약을 정확히 지키는 출력의 빠른 경로다. 표준 JSON 파싱을
    먼저 시도하고, trailing comma·LaTeX 백슬래시 등으로 실패하면 관용 파서로 한 번 더
    시도한다. 두 시도 모두 실패하면 원인을 담은 ConversionError를 올린다 — 빈 값으로
    삼키면 정답 계약이 조용히 깨지므로 금지한다.
    """
    block = _extract_json_object(text)
    try:
        payload = GeneratedLessonPayload.model_validate(_normalized_data(block))
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ConversionError(f"ChapterStudio JSON 검증 실패: {exc}") from exc
    _validate_indices(payload, slide_count)
    return payload


def parse_payload_lenient(text: str) -> LenientLessonPayload:
    """배열 개수·인덱스 계약을 강제하지 않고 관대하게 1차 파싱한다(부족 허용).

    항목 구조·타입은 여전히 strict 검증한다. backfill 단계가 부족분을 채운 뒤
    finalize_payload가 최종 엄격 계약을 강제한다. 파싱 자체가 불가능하면(구조 손상)
    ConversionError로 드러낸다 — 빈 값으로 삼키지 않는다.
    """
    block = _extract_json_object(text)
    try:
        return LenientLessonPayload.model_validate(_normalized_data(block))
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ConversionError(f"ChapterStudio JSON 관대 검증 실패: {exc}") from exc


def finalize_payload(lenient: LenientLessonPayload, slide_count: int) -> GeneratedLessonPayload:
    """관대 payload(보충 완료분)를 최종 엄격 모델로 승격하고 계약을 강제한다.

    개수·slide_idx 완전집합 계약이 충족되지 않으면 ConversionError를 올린다 —
    다운스트림 persistence가 이 계약에 의존하므로 절대 통과시키지 않는다.
    """
    try:
        payload = GeneratedLessonPayload.model_validate(lenient.model_dump())
    except (ValidationError, ValueError) as exc:
        raise ConversionError(f"ChapterStudio 최종 검증 실패: {exc}") from exc
    _validate_indices(payload, slide_count)
    return payload


def _normalized_data(block: str) -> dict[str, object]:
    """추출된 JSON 블록을 관용 파싱한 뒤 dict→list 정규화 패스를 적용한다."""
    data = loads_lenient(block)
    return normalize_lesson_dict(data)


def payload_from_state_dict(data: dict[str, object]) -> GeneratedLessonPayload:
    """generate 노드가 stash한 payload dict를 strict 모델로 되살린다.

    content_verify 노드가 중간 버킷(lesson_payload)에서 payload를 복원할 때 쓴다. 형태가
    깨졌으면 strict 검증이 ConversionError로 드러낸다(빈 값으로 삼키지 않는다).
    """
    try:
        return GeneratedLessonPayload.model_validate(data)
    except (ValidationError, ValueError) as exc:
        raise ConversionError(f"lesson_payload 복원 실패: {exc}") from exc


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
    """모델 응답에서 첫 유효 JSON 객체를 꺼낸다.

    공통 유틸(common.llm_output)로 reasoning(<think>)·마크다운 펜스·앞뒤 잡텍스트를 먼저
    제거한 뒤 괄호 깊이 추적으로 객체를 잘라낸다. Qwen 스왑 시 흔한 think-laden 출력을
    프로덕션 경로에서도 방어하기 위함이다.
    """
    cleaned = strip_thinking(text)
    block = extract_json_block(cleaned)
    if not block.startswith("{"):
        raise ValueError("JSON 객체 시작 문자가 없다.")
    return block


__all__ = [
    "GeneratedLessonPayload",
    "LenientLessonPayload",
    "parse_payload",
    "parse_payload_lenient",
    "finalize_payload",
    "payload_from_state_dict",
]
