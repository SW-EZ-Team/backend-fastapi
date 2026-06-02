"""컴포넌트 병렬 생성용 프롬프트 빌더와 응답 파서."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.postprocess.visual_renderers import render_fallback_visual, render_visual_slide
from app.modules.ChapterStudio_V1.pipeline.normalize import normalize_assignment_value
from app.modules.ChapterStudio_V1.pipeline.parallel_prompt_text import (
    assignment_prompts,
    clean_raw_voice_text as _clean_raw_voice_text,
    note_prompts,
    quizzes_prompts,
    slides_prompts,
    voice_prompt,
)
from app.modules.ChapterStudio_V1.pipeline.parallel_inputs import PersonalizationArgs
from app.modules.ChapterStudio_V1.pipeline.payload import (
    GeneratedAssignment,
    GeneratedNoteBlock,
    GeneratedQuiz,
    GeneratedSlide,
    GeneratedVoiceScript,
    SlideCategory,
)
from common.llm_output import extract_json_block, loads_lenient, strip_thinking

# 컴포넌트별 토큰 상한 — 작은 단일목적 응답에 맞춰 여유 있게 잡는다.
_SLIDES_MAX_TOKENS = 16000
_QUIZZES_MAX_TOKENS = 9000
_NOTE_MAX_TOKENS = 4000
_ASSIGNMENT_MAX_TOKENS = 4000
_VOICE_MAX_TOKENS = 4000
VisualSlideCategory = Literal["text", "diagram", "math", "chart"]


class _SlidesResult(BaseModel):
    """slides 스키마 응답 — slides 배열만 담는다."""

    model_config = ConfigDict(strict=True)

    slides: list[GeneratedSlide] = Field(min_length=1, max_length=15)


class _VisualSpecResult(BaseModel):
    """Qwen slides 스키마의 구조화 visual 객체다."""

    model_config = ConfigDict(strict=True)

    type: str = Field(min_length=1)
    data: dict[str, object]


class _VisualSlideResult(BaseModel):
    """raw HTML 대신 받은 슬라이드 visual 스펙이다."""

    model_config = ConfigDict(strict=True)

    slide_idx: int = Field(ge=0, le=14)
    title: str = Field(min_length=1)
    category: VisualSlideCategory
    narration: str = Field(min_length=1, max_length=420)
    visual: _VisualSpecResult
    checkpoint: str = Field(min_length=1)


class _QuizzesResult(BaseModel):
    """quizzes 스키마 응답 — quizzes 배열만 담는다."""

    model_config = ConfigDict(strict=True)

    quizzes: list[GeneratedQuiz] = Field(max_length=15)


class _NoteResult(BaseModel):
    """note 스키마 응답 — note_blocks 배열만 담는다."""

    model_config = ConfigDict(strict=True)

    note_blocks: list[GeneratedNoteBlock] = Field(min_length=3, max_length=5)


class _AssignmentResult(BaseModel):
    """assignment 스키마 응답 — assignment 객체만 담는다."""

    model_config = ConfigDict(strict=True)

    assignment: GeneratedAssignment


def build_slides_request(
    brief: str, outline: str, slide_count: int, template_key: str, personalization: PersonalizationArgs
) -> ChapterAIRequest:
    """슬라이드 배열만 생성하는 요청을 만든다(schema_kind=slides)."""
    system, user = slides_prompts(brief, outline, slide_count, template_key, **_prompt_kwargs(personalization))
    return _request(system, user, _SLIDES_MAX_TOKENS, 0.35, slide_count, "slides", template_key)


def build_quizzes_request(
    brief: str, outline: str, slide_count: int, template_key: str, personalization: PersonalizationArgs
) -> ChapterAIRequest:
    """퀴즈 배열만 생성하는 요청을 만든다(schema_kind=quizzes)."""
    system, user = quizzes_prompts(brief, outline, slide_count, **_prompt_kwargs(personalization))
    return _request(system, user, _QUIZZES_MAX_TOKENS, 0.3, slide_count, "quizzes", template_key)


def build_note_request(
    brief: str, outline: str, slide_count: int, template_key: str, personalization: PersonalizationArgs
) -> ChapterAIRequest:
    """핵심 노트(note_blocks)만 생성하는 요청을 만든다(schema_kind=note)."""
    system, user = note_prompts(brief, outline, **_prompt_kwargs(personalization))
    return _request(system, user, _NOTE_MAX_TOKENS, 0.3, slide_count, "note", template_key)


def build_assignment_request(
    brief: str, outline: str, slide_count: int, template_key: str, personalization: PersonalizationArgs
) -> ChapterAIRequest:
    """과제(assignment)만 생성하는 요청을 만든다(schema_kind=assignment)."""
    system, user = assignment_prompts(brief, outline, **_prompt_kwargs(personalization))
    return _request(system, user, _ASSIGNMENT_MAX_TOKENS, 0.3, slide_count, "assignment", template_key)


def build_voice_request(
    brief: str,
    slide_title: str,
    slide_focus: str,
    slide_summary: str,
    previous_title: str,
    slide_idx: int,
    slide_count: int,
    personalization: PersonalizationArgs,
) -> ChapterAIRequest:
    """슬라이드 1개의 음성대본만 생성하는 요청을 만든다(schema_kind=voice_script)."""
    system, user = voice_prompt(
        brief,
        slide_title,
        slide_focus,
        slide_summary,
        slide_idx,
        previous_title=previous_title,
        **_prompt_kwargs(personalization),
    )
    return ChapterAIRequest(
        system=system,
        user=user,
        max_tokens=_VOICE_MAX_TOKENS,
        temperature=0.3,
        extra={"schema": "voice_script", "slide_count": slide_count, "slide_idx": slide_idx},
    )


def parse_slides(text: str) -> list[GeneratedSlide]:
    """slides 응답에서 legacy HTML 또는 구조화 visual 스펙을 strict 검증해 꺼낸다."""
    data = _loaded(text)
    raw_slides = _raw_slides(data)
    return [_parse_slide_item(item) for item in raw_slides]


def parse_quizzes(text: str) -> list[GeneratedQuiz]:
    """quizzes 응답에서 quizzes 배열을 strict 검증해 꺼낸다."""
    return _QuizzesResult.model_validate(_loaded(text)).quizzes


def parse_note(text: str) -> list[GeneratedNoteBlock]:
    """note 응답에서 note_blocks 배열을 strict 검증해 꺼낸다."""
    return _NoteResult.model_validate(_loaded(text)).note_blocks


def parse_assignment(text: str) -> GeneratedAssignment:
    """assignment 응답을 strict 검증해 꺼낸다(steps/rubric dict는 사전 정규화)."""
    data = _loaded(text)
    if isinstance(data, dict) and isinstance(data.get("assignment"), dict):
        data = {**data, "assignment": normalize_assignment_value(data["assignment"])}
    return _AssignmentResult.model_validate(data).assignment


def parse_voice(text: str, slide_idx: int) -> GeneratedVoiceScript:
    """voice JSON을 파싱하고 raw 대본 반환 케이스는 slide_idx를 유지해 폴백한다."""
    from app.modules.ChapterStudio_V1.common.logging import logger  # 지역 import — 순환 방지
    try:
        return GeneratedVoiceScript.model_validate(_loaded(text))
    except (ValueError, ValidationError) as exc:
        # Qwen이 guided_json 대신 대본만 반환한 경우에도 호출부의 slide_idx를 보존한다.
        script_text = _clean_raw_voice_text(text)
        logger.warning(
            "parse_voice: JSON 파싱 실패(slide_idx={}) → raw 텍스트 폴백 사용 "
            "({}자, 원인: {})",
            slide_idx,
            len(script_text),
            exc,
        )
        return GeneratedVoiceScript(slide_idx=slide_idx, script_text=script_text)


def _loaded(text: str) -> object:
    """모델 응답에서 JSON 블록을 꺼내 관용 파싱한다(think·fence 제거 후)."""
    return loads_lenient(extract_json_block(strip_thinking(text)))


def _raw_slides(data: object) -> list[object]:
    if not isinstance(data, dict) or not isinstance(data.get("slides"), list):
        raise ValueError("slides 배열이 필요하다.")
    raw = data["slides"]
    if not 1 <= len(raw) <= 15:
        raise ValueError("slides 개수가 허용 범위를 벗어났다.")
    return raw


def _parse_slide_item(item: object) -> GeneratedSlide:
    if not isinstance(item, Mapping):
        raise ValueError("slides 항목은 객체여야 한다.")
    data = dict(item)
    if isinstance(data.get("visual"), Mapping):
        try:
            return _visual_slide_to_generated(_VisualSlideResult.model_validate(data))
        except ValidationError:
            return _fallback_slide(data)
    if "html" not in data:
        return _fallback_slide(data)
    return GeneratedSlide.model_validate(data)


def _visual_slide_to_generated(item: _VisualSlideResult) -> GeneratedSlide:
    visual_data = item.visual.model_dump()
    html = render_visual_slide(item.title, item.narration, item.visual.type, item.visual.data)
    return GeneratedSlide(
        slide_idx=item.slide_idx,
        title=item.title,
        focus=item.narration,
        checkpoint=item.checkpoint,
        category=_slide_category(item.category),
        html=html,
        css="",
        narration=item.narration,
        visual=visual_data,
    )


def _slide_category(category: VisualSlideCategory) -> SlideCategory:
    return category


def _fallback_slide(data: dict[object, object]) -> GeneratedSlide:
    slide_idx = data.get("slide_idx")
    if not isinstance(slide_idx, int):
        raise ValueError("slide_idx 정수가 필요하다.")
    title = _text_value(data.get("title"), f"슬라이드 {slide_idx + 1}")
    narration = _fallback_narration(data, title)
    checkpoint = _text_value(data.get("checkpoint"), "핵심 조건을 말로 확인할 수 있는가?")
    category = _category_value(data.get("category"))
    html = render_fallback_visual(title, narration)
    return GeneratedSlide(
        slide_idx=slide_idx,
        title=title,
        focus=narration,
        checkpoint=checkpoint,
        category=category,
        html=html,
        css="",
        narration=narration,
        visual={"type": "example_box", "data": {"problem": title, "steps": [narration], "answer": checkpoint}},
    )


def _text_value(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _fallback_narration(data: dict[object, object], title: str) -> str:
    """빈 narration을 실제 슬라이드 맥락에서 만든 문장으로 대체한다."""
    raw = _text_value(data.get("narration"), "")
    if _is_specific_narration(raw):
        return raw.strip()
    voice_text = _voice_text(data.get("voice_script")) or _text_value(data.get("script_text"), "")
    if _is_specific_narration(voice_text):
        return _compact_sentences(voice_text)
    focus_text = _first_specific_text(data, ("focus", "summary", "description", "role"))
    if focus_text:
        return _title_focus_sentence(title, focus_text)
    return _title_focus_sentence(title, "")


def _voice_text(value: object) -> str:
    """voice_script가 같은 객체에 들어온 legacy 응답이면 본문 후보로 꺼낸다."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        script = value.get("script_text")
        return script.strip() if isinstance(script, str) else ""
    return ""


def _first_specific_text(data: dict[object, object], keys: tuple[str, ...]) -> str:
    """focus·summary 계열 필드에서 플레이스홀더가 아닌 첫 문장을 찾는다."""
    for key in keys:
        value = _text_value(data.get(key), "")
        if _is_specific_narration(value):
            return value.strip()
    return ""


def _title_focus_sentence(title: str, focus: str) -> str:
    """voice가 없을 때 제목과 초점만으로도 화면 본문이 비지 않게 만든다."""
    if focus:
        normalized = focus.rstrip(".!?。！？")
        return _compact_sentences(f"{title}에서는 {normalized}. 이 기준을 실제 예시에 적용해 확인합니다.")
    return f"{title}에서는 핵심 기준을 실제 예시와 연결해 확인합니다."


def _compact_sentences(text: str, max_chars: int = 360) -> str:
    """긴 음성대본에서 앞쪽 1~2문장만 뽑아 화면 본문 길이로 줄인다."""
    cleaned = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    sentences = re.findall(r"[^.!?。！？]+[.!?。！？]?", cleaned)
    compact = " ".join(part.strip() for part in sentences[:2] if part.strip()) or cleaned
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rsplit(" ", 1)[0].strip() or compact[:max_chars].strip()


def _is_specific_narration(value: str) -> bool:
    """빈 값과 기존 generic fallback 문구를 실제 본문 후보에서 제외한다."""
    text = value.strip()
    if not text:
        return False
    placeholders = {
        "시각 자료",
        "핵심 조건을 다시 확인한다",
        "핵심 조건을 다시 확인한다.",
        "핵심 내용을 예제 카드로 정리한다",
        "핵심 내용을 예제 카드로 정리한다.",
        "핵심을 시각적으로 확인한다",
        "핵심을 시각적으로 확인한다.",
    }
    return text not in placeholders


def _category_value(value: object) -> SlideCategory:
    if isinstance(value, str) and value in {"text", "diagram", "math", "chart"}:
        return cast(SlideCategory, value)
    return "text"


def _request(
    system: str, user: str, max_tokens: int, temperature: float, slide_count: int, schema: str, template_key: str
) -> ChapterAIRequest:
    return ChapterAIRequest(
        system=system,
        user=user,
        max_tokens=max_tokens,
        temperature=temperature,
        extra={"schema": schema, "slide_count": slide_count, "template_key": template_key},
    )


def _prompt_kwargs(personalization: PersonalizationArgs) -> dict[str, str | int | bool]:
    return {
        "weak_points": personalization.weak_points,
        "audience_level": personalization.audience_level,
        "tone": personalization.tone,
        "pace": personalization.pace,
        "tutor_depth": personalization.tutor_depth,
        "socratic": personalization.socratic,
        "learning_goal": personalization.learning_goal,
        "use_formal_speech": personalization.use_formal_speech,
        "use_emoji": personalization.use_emoji,
        "tutor_name": personalization.tutor_name,
        "tutor_tagline": personalization.tutor_tagline,
        "is_default_tutor": personalization.is_default_tutor,
        "voice_sample_url": personalization.voice_sample_url,
    }


__all__ = [
    "build_assignment_request",
    "build_note_request",
    "build_quizzes_request",
    "build_slides_request",
    "build_voice_request",
    "parse_assignment",
    "parse_note",
    "parse_quizzes",
    "parse_slides",
    "parse_voice",
]
