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
from app.modules.ChapterStudio_V1.app.template_types import VISUAL_TYPE_ALIASES
from app.modules.ChapterStudio_V1.postprocess.title_rules import relabel_chapter_title as _relabel_title
from common.llm_output import extract_json_block, loads_lenient, strip_thinking

# 컴포넌트별 토큰 상한 — 작은 단일목적 응답에 맞춰 여유 있게 잡는다.
# gemini_flash가 활성 텍스트 모델이면 thinking 토큰(~21000)이 max_output_tokens 예산을 먼저
# 잠식한다(이 병렬 경로는 connector.supports("batch")=True인 Qwen Modal 전용이라 현재 gemini에선
# 휴면이나, ACTIVE_TEXT_MODEL 전환 시 즉시 활성). thinking 헤드룸을 포함해 본문성(slides)=40000,
# quizzes=32000, 짧은 보조(note/assignment/voice)=24000으로 통일한다(메인노드 48000과 정합, 한도 65536).
_SLIDES_MAX_TOKENS = 40000
_QUIZZES_MAX_TOKENS = 32000
_NOTE_MAX_TOKENS = 24000
_ASSIGNMENT_MAX_TOKENS = 24000
_VOICE_MAX_TOKENS = 24000
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
    # 프롬프트 지시(200~360자)보다 여유 있게 잡아 AI가 약간 길게 생성해도 ValidationError로
    # fallback 경로가 열리지 않게 한다. 진짜 이상값(600자 초과)은 fallback이 처리한다.
    narration: str = Field(min_length=1, max_length=600)
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
    brief: str,
    outline: str,
    slide_count: int,
    template_key: str,
    personalization: PersonalizationArgs,
    slide_plan: list[dict[str, object]] | None = None,
) -> ChapterAIRequest:
    """슬라이드 배열만 생성하는 요청을 만든다(schema_kind=slides).

    slide_plan이 주어지면 plan이 쓰는 visual.type 집합을 extra.plan_visual_types로 전달해
    Modal guided 스키마가 enum을 그 집합으로 좁히게 한다(P1 — schema narrowing).
    per-slot 단일값 강제는 parse_slides backstop이 담당하며, 여기서는 집합만 좁힌다.
    """
    system, user = slides_prompts(brief, outline, slide_count, template_key, **_prompt_kwargs(personalization))
    req = _request(system, user, _SLIDES_MAX_TOKENS, 0.35, slide_count, "slides", template_key)
    plan_types = _plan_visual_types_csv(slide_plan)
    if plan_types:
        # extra 값은 스칼라만 허용되므로 콤마 결합 문자열로 전달한다(modal_app가 역파싱).
        req.extra["plan_visual_types"] = plan_types
    return req


def _plan_visual_types_csv(slide_plan: list[dict[str, object]] | None) -> str:
    """slide_plan에서 쓰이는 visual.type 집합을 콤마 결합 문자열로 만든다(중복 제거·순서 보존)."""
    if not slide_plan:
        return ""
    seen: set[str] = set()
    ordered: list[str] = []
    for slot in slide_plan:
        if not isinstance(slot, dict):
            continue
        vt = slot.get("visual_type")
        if isinstance(vt, str) and vt and vt not in seen:
            seen.add(vt)
            ordered.append(vt)
    return ",".join(ordered)


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


def parse_slides(
    text: str,
    slide_plan: list[dict[str, object]] | None = None,
) -> list[GeneratedSlide]:
    """slides 응답에서 visual 스펙을 검증해 꺼낸다.

    slide_plan이 주어지면 각 슬롯의 visual.type을 플랜과 대조한다:
    - AI 반환 type이 플랜과 다르면 플랜 type으로 강제 정규화(silent 드리프트 차단).
    - 챕터명+번호 형태 제목은 must_have 기반 결정적 재라벨로 교체한다.
    """
    data = _loaded(text)
    raw_slides = _raw_slides(data)
    plan_map = _build_plan_map(slide_plan)
    return [_parse_slide_item(item, plan_map.get(_slide_idx(item))) for item in raw_slides]


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
    """voice JSON을 파싱한다. sections 형식(plan-first) 또는 legacy script_text 형식 모두 처리.

    파싱 우선순위:
    1. sections 배열이 있으면 VoiceSection 목록으로 검증 → script_text 파생.
    2. script_text만 있으면 레거시 경로로 처리(하위호환).
    3. JSON 파싱 자체 실패면 raw 텍스트 폴백(slide_idx 보존).
    """
    from app.modules.ChapterStudio_V1.common.logging import logger  # 지역 import — 순환 방지
    try:
        data = _loaded(text)
        if isinstance(data, dict) and "sections" in data:
            # plan-first 경로: sections 배열 포함 → GeneratedVoiceScript가 join 파생.
            # slide_idx가 없으면 호출부 값으로 보완한다.
            if "slide_idx" not in data:
                data = {**data, "slide_idx": slide_idx}
            return GeneratedVoiceScript.model_validate(data)
        # 레거시 경로: script_text만 있는 경우.
        return GeneratedVoiceScript.model_validate(data)
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


def _parse_slide_item(
    item: object,
    plan_slot: dict[str, object] | None = None,
) -> GeneratedSlide:
    if not isinstance(item, Mapping):
        raise ValueError("slides 항목은 객체여야 한다.")
    data = dict(item)
    if isinstance(data.get("visual"), Mapping):
        # plan 대조: visual.type을 플랜으로 정규화한다(silent 드리프트 차단).
        data = _enforce_plan_visual_type(data, plan_slot)
        try:
            result = _VisualSlideResult.model_validate(data)
        except ValidationError:
            # 검증 실패(예: category=interactive/code 등 Literal 미포함)해도 plan visual_type은
            # 보존한다. plan_slot을 넘겨 example_box 하드코딩 드리프트를 막는다(P2).
            return _fallback_slide(data, plan_slot)
        # raw_data를 함께 전달해 불완결 narration 보완에 voice_script를 활용할 수 있게 한다.
        return _visual_slide_to_generated(result, plan_slot, raw_data=data)
    if "html" not in data:
        return _fallback_slide(data, plan_slot)
    return GeneratedSlide.model_validate(data)


def _visual_slide_to_generated(
    item: _VisualSlideResult,
    plan_slot: dict[str, object] | None = None,
    raw_data: dict[str, object] | None = None,
) -> GeneratedSlide:
    visual_data = item.visual.model_dump()
    # 챕터명+번호 형태 제목은 결정적 재라벨로 교체한다.
    title = _relabel_chapter_title(item.title, plan_slot)
    narration = item.narration
    # AI narration 완결성 검증: 불완결이면 voice_script 보완을 시도한다.
    # AI max_tokens 초과로 JSON narration 문자열이 중간에 절단된 경우를 처리한다.
    if not _is_complete_narration(narration):
        from app.modules.ChapterStudio_V1.common.logging import logger  # 지역 import — 순환 방지
        logger.warning(
            "_visual_slide_to_generated: slide_idx={} narration이 불완결로 끝남 "
            "(마지막 15자: {}). 보완 시도.",
            item.slide_idx,
            repr(narration[-15:]),
        )
        if raw_data is not None:
            # 보완 우선순위: voice_script → script_text → focus/summary/description
            voice_text = _voice_text(raw_data.get("voice_script")) or _text_value(
                raw_data.get("script_text"), ""
            )
            if _is_specific_narration(voice_text):
                narration = _compact_sentences(voice_text)
                logger.info(
                    "_visual_slide_to_generated: slide_idx={} voice_script 보완 성공 ({}자).",
                    item.slide_idx,
                    len(narration),
                )
            else:
                # voice도 없으면 focus/summary에서 title-focus 문장 생성
                focus_text = _first_specific_text(
                    raw_data,
                    ("focus", "summary", "description"),
                )
                if focus_text:
                    narration = _title_focus_sentence(title, focus_text)
                    logger.info(
                        "_visual_slide_to_generated: slide_idx={} focus 기반 보완 ({}자).",
                        item.slide_idx,
                        len(narration),
                    )
    html = render_visual_slide(title, narration, item.visual.type, item.visual.data)
    return GeneratedSlide(
        slide_idx=item.slide_idx,
        title=title,
        focus=narration,
        checkpoint=item.checkpoint,
        category=_slide_category(item.category),
        html=html,
        css="",
        narration=narration,
        visual=visual_data,
    )


# ---------------------------------------------------------------------------
# plan-first 대조 헬퍼 함수들
# ---------------------------------------------------------------------------


def _build_plan_map(
    slide_plan: list[dict[str, object]] | None,
) -> dict[int, dict[str, object]]:
    """slide_plan 목록을 slide_idx 키 dict로 변환한다."""
    if not slide_plan:
        return {}
    result: dict[int, dict[str, object]] = {}
    for slot in slide_plan:
        if isinstance(slot, dict):
            idx = slot.get("slide_idx")
            if isinstance(idx, int):
                result[idx] = slot
    return result


def _slide_idx(item: object) -> int:
    """raw dict 항목에서 slide_idx를 꺼낸다. 없으면 -1."""
    if isinstance(item, Mapping):
        idx = item.get("slide_idx")
        if isinstance(idx, int):
            return idx
    return -1


def _normalize_visual_type(vt: str) -> str:
    """하이픈·언더스코어 혼용 alias를 정규화한다."""
    return VISUAL_TYPE_ALIASES.get(vt, vt)


def _enforce_plan_visual_type(
    data: dict[str, object],
    plan_slot: dict[str, object] | None,
) -> dict[str, object]:
    """AI 반환 visual.type을 플랜 type과 대조해 다르면 플랜 type으로 강제 교체한다.

    plan-first 원칙: type 결정권은 코드에 있고 AI는 data만 채운다.
    alias 정규화 후 비교한다(comparison_table == comparison-table).
    """
    if plan_slot is None:
        return data
    plan_vt = plan_slot.get("visual_type")
    if not isinstance(plan_vt, str) or not plan_vt:
        return data
    visual = data.get("visual")
    if not isinstance(visual, Mapping):
        return data
    ai_vt = visual.get("type")
    if not isinstance(ai_vt, str):
        # type 자체 누락 → 플랜 type 삽입
        data = {**data, "visual": {**dict(visual), "type": plan_vt}}
        return data
    # alias 정규화 후 비교: 다르면 플랜 type으로 교체
    if _normalize_visual_type(ai_vt) != _normalize_visual_type(plan_vt):
        data = {**data, "visual": {**dict(visual), "type": plan_vt}}
    return data


def _relabel_chapter_title(title: str, plan_slot: dict[str, object] | None) -> str:
    """챕터명+번호 형태 제목을 plan.must_have 기반으로 결정적 재라벨한다.

    감지·재라벨 로직은 title_rules.relabel_chapter_title(단일 진실 소스)에 위임한다.
    plan_slot이 없으면 원본 유지(대조 기준이 없으므로 변경하지 않는다).
    """
    if plan_slot is None:
        return title
    must_have = plan_slot.get("must_have")
    if not isinstance(must_have, list):
        return title
    return _relabel_title(title, must_have)


def _slide_category(category: VisualSlideCategory) -> SlideCategory:
    return category


def _fallback_slide(
    data: dict[object, object],
    plan_slot: dict[str, object] | None = None,
) -> GeneratedSlide:
    slide_idx = data.get("slide_idx")
    if not isinstance(slide_idx, int):
        raise ValueError("slide_idx 정수가 필요하다.")
    title = _relabel_chapter_title(_text_value(data.get("title"), f"슬라이드 {slide_idx + 1}"), plan_slot)
    narration = _fallback_narration(data, title)
    checkpoint = _text_value(data.get("checkpoint"), "핵심 조건을 말로 확인할 수 있는가?")
    category = _category_value(data.get("category"))
    visual_type, visual_data = _fallback_visual(data, plan_slot, title, narration, checkpoint)
    # plan visual_type이 있으면 그 타입 렌더러로, 없으면 안전한 example_box 폴백으로 그린다.
    html = (
        render_visual_slide(title, narration, visual_type, visual_data)
        if visual_type != "example_box"
        else render_fallback_visual(title, narration)
    )
    return GeneratedSlide(
        slide_idx=slide_idx,
        title=title,
        focus=narration,
        checkpoint=checkpoint,
        category=category,
        html=html,
        css="",
        narration=narration,
        visual={"type": visual_type, "data": visual_data},
    )


def _fallback_visual(
    data: dict[object, object],
    plan_slot: dict[str, object] | None,
    title: str,
    narration: str,
    checkpoint: str,
) -> tuple[str, dict[str, object]]:
    """폴백 슬라이드의 visual.type을 결정한다.

    plan visual_type이 있으면(이미 _enforce_plan_visual_type이 data.visual.type에 반영) 그 타입을
    유지해 드리프트를 막는다(P2). AI가 준 visual.data가 있으면 재사용하고, 없으면 example_box 폴백
    형태의 안전한 data를 만든다.
    """
    plan_vt = plan_slot.get("visual_type") if isinstance(plan_slot, dict) else None
    example_data: dict[str, object] = {"problem": title, "steps": [narration], "answer": checkpoint}
    if not isinstance(plan_vt, str) or not plan_vt:
        return "example_box", example_data
    ai_visual = data.get("visual")
    ai_data = ai_visual.get("data") if isinstance(ai_visual, Mapping) else None
    return _normalize_visual_type(plan_vt), dict(ai_data) if isinstance(ai_data, Mapping) else example_data


def _text_value(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _is_complete_narration(text: str) -> bool:
    """narration이 완결 문장으로 끝나는지 판단한다.

    JSON max_tokens 초과로 AI 응답이 문장 중간에 절단된 경우를 감지한다.
    한국어 종결 어미(다/요/죠/지/고 등)·마침표·느낌표·물음표·완전한 단어 종료를 확인한다.
    """
    if not text:
        return False
    stripped = text.strip()
    # 명백한 종결 부호: 마침표·느낌표·물음표·한국어 문장 종결 부호
    if stripped[-1] in ".!?。！？":
        return True
    # 한국어 일반적 종결 어미들 — 실제 마지막 어절 기준
    last_word = stripped.rsplit(" ", 1)[-1] if " " in stripped else stripped
    korean_endings = (
        "습니다", "합니다", "입니다", "됩니다", "있습니다", "없습니다",
        "했습니다", "됐습니다", "했어요", "돼요", "해요", "있어요", "없어요",
        "봐요", "줘요", "세요", "아요", "어요", "이에요", "예요",
        "구나", "군요", "네요", "죠", "지요",
        "는다", "ㄴ다", "ㄹ까", "ㄹ게",
    )
    return any(last_word.endswith(ending) for ending in korean_endings)


def _fallback_narration(data: dict[object, object], title: str) -> str:
    """빈 또는 불완결 narration을 실제 슬라이드 맥락에서 완결 문장으로 보완한다.

    1) raw narration이 있고 완결 문장이면 그대로 사용한다.
    2) raw narration이 있지만 불완결(AI max_tokens 절단)이면 voice_script로 보완을 시도한다.
       보완에 성공하면 voice_text 기반 compact를 사용한다.
    3) raw가 없으면 voice_script → focus → title 순서로 fallback한다.
    """
    raw = _text_value(data.get("narration"), "")
    if _is_specific_narration(raw):
        stripped = raw.strip()
        if _is_complete_narration(stripped):
            # 완결 narration은 그대로 반환한다.
            return stripped
        # 불완결 narration: voice_script로 보완을 시도한다.
        voice_text = _voice_text(data.get("voice_script")) or _text_value(data.get("script_text"), "")
        if _is_specific_narration(voice_text):
            return _compact_sentences(voice_text)
        # voice도 없으면 불완결 raw 대신 focus 기반으로 대체한다.
        focus_text = _first_specific_text(data, ("focus", "summary", "description", "role"))
        if focus_text:
            return _title_focus_sentence(title, focus_text)
        return _title_focus_sentence(title, "")
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


def _first_specific_text(data: dict[str, object], keys: tuple[str, ...]) -> str:
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
    """긴 음성대본에서 앞쪽 완결 문장만 뽑아 화면 본문 길이로 줄인다.

    문장 경계(종결 어미·부호)를 단위로 자르므로 단어·어미 중간 절단이 발생하지 않는다.
    - max_chars 이하인 완결 문장 누적을 반환한다.
    - 첫 문장 자체가 max_chars를 초과하면 해당 문장 전체를 반환한다(절단 금지).
    """
    cleaned = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    sentences = [s.strip() for s in re.findall(r"[^.!?。！？]+[.!?。！？]?", cleaned) if s.strip()]
    if not sentences:
        return cleaned[:max_chars] if len(cleaned) > max_chars else cleaned
    # 완결 문장을 하나씩 추가하면서 max_chars를 넘지 않는 최대 지점을 찾는다.
    result_parts: list[str] = []
    accumulated = 0
    for sent in sentences:
        new_len = accumulated + len(sent) + (1 if result_parts else 0)
        if new_len <= max_chars:
            result_parts.append(sent)
            accumulated = new_len
        else:
            break
    # 하나도 못 담은 경우(첫 문장 자체가 max_chars 초과): 문장 전체를 반환해 절단하지 않는다.
    if not result_parts:
        return sentences[0]
    return " ".join(result_parts)


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
    "_enforce_plan_visual_type",
    "_relabel_chapter_title",
    "_normalize_visual_type",
    "_is_complete_narration",
    "_compact_sentences",
]
