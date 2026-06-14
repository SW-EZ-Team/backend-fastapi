"""컴포넌트 병렬 강의 생성 오케스트레이션(Qwen Modal 전용 경로).

connector.supports("batch")가 True일 때(=Qwen Modal) 강의 1개의 산출물을 컴포넌트 단위로
동시 생성한다. 단일 거대 콜에서 Qwen이 뒤쪽 배열을 적게 만들고 rubric을 dict로 내던 실측
오류를, 작은 단일목적 guided JSON 스키마 + 병렬 호출로 회피한다.

동시 호출(asyncio.gather):
    1단계 slides ‖ quizzes ‖ note ‖ assignment
    2단계 생성된 slide 화면 요약을 넣어 voice_scripts(슬라이드별 N개) 병렬 생성
B200 max_inputs=8가 동시 입력을 처리한다.

설계 원칙(정직하게):
    - return_exceptions로 항목별 예외를 받아 한 컴포넌트 실패가 전체로 번지지 않게 한다.
    - 실패 컴포넌트만 1회 재시도한다(무한루프 없음). 재시도도 실패하면 명확한 에러로 드러낸다.
    - rubric/steps가 dict면 list로 정규화한다(파서 내부에서 처리).
    - 최종 조립은 finalize_payload가 개수·slide_idx 완전집합 계약을 강제한다(삼키지 않음).

공개 API:
    - generate_lesson_parallel(connector, state, slide_count) -> GeneratedLessonPayload
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from functools import partial
from typing import TypeVar, cast

from pydantic import ValidationError

from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector
from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.common.logging import logger
from app.modules.ChapterStudio_V1.pipeline import parallel_prompts as pp
from app.modules.ChapterStudio_V1.pipeline.parallel_assemble import (
    ComponentBundle,
    assemble_payload,
)
from app.modules.ChapterStudio_V1.pipeline.parallel_inputs import (
    PersonalizationArgs,
    VoiceTarget,
    build_brief,
    build_outline_text,
    build_personalization_args,
    build_reference_block,
    build_voice_targets,
)
from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload, GeneratedSlide
from app.modules.ChapterStudio_V1.pipeline.slide_plan import build_slide_plan, serialize_slide_plan
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState

_Result = TypeVar("_Result")

# 컴포넌트 생성 실패 시 재시도 횟수 — 1회만(무한루프 방지).
_RETRY_ATTEMPTS = 1


async def generate_lesson_parallel(
    connector: AIConnector, state: ChapterStudioState, slide_count: int
) -> GeneratedLessonPayload:
    """컴포넌트별 병렬 생성 → 조립 → 계약 강제로 강의 payload를 만든다(Qwen Modal 경로)."""
    brief = build_brief(state)
    outline = build_outline_text(state, slide_count)
    template_key = _template_key(state)
    personalization = build_personalization_args(state)
    # PDF 소스 강의의 참고도서 발췌 — 단일콜 경로(prompt.py)와 동일하게 병렬 경로에도 주입한다.
    reference_block = build_reference_block(state)

    bundle = await _gather_components(
        connector, state, brief, outline, template_key, slide_count, personalization, reference_block
    )
    return assemble_payload(bundle, slide_count)


async def _gather_components(
    connector: AIConnector,
    state: ChapterStudioState,
    brief: str,
    outline: str,
    template_key: str,
    slide_count: int,
    personalization: PersonalizationArgs,
    reference_block: str = "",
) -> ComponentBundle:
    """코어 컴포넌트 생성 후 화면 내용 기반 voice를 생성한다."""
    # plan-first 강제: context_node가 채운 slide_outline(visual_type 포함)을 parse_slides의
    # slide_plan으로 바인딩한다. 이렇게 해야 _enforce_plan_visual_type / _relabel_chapter_title이
    # 프로덕션 경로에서 실제로 작동한다(함수참조만 넘기면 slide_plan=None이라 강제가 죽는다).
    slide_plan_rows = _resolve_slide_plan(state, template_key, slide_count)
    slides_parse = partial(pp.parse_slides, slide_plan=slide_plan_rows)
    slides_task = _component(
        connector,
        # plan을 build_slides_request에도 넘겨 Modal guided enum을 plan 집합으로 좁힌다(P1).
        pp.build_slides_request(
            brief, outline, slide_count, template_key, personalization, slide_plan_rows, reference_block
        ),
        slides_parse,
    )
    quizzes_task = _component(
        connector,
        pp.build_quizzes_request(brief, outline, slide_count, template_key, personalization, reference_block),
        pp.parse_quizzes,
    )
    note_task = _component(
        connector,
        pp.build_note_request(brief, outline, slide_count, template_key, personalization, reference_block),
        pp.parse_note,
    )
    assignment_task = _component(
        connector,
        pp.build_assignment_request(brief, outline, slide_count, template_key, personalization, reference_block),
        pp.parse_assignment,
    )
    slides, quizzes, note_blocks, assignment = await asyncio.gather(slides_task, quizzes_task, note_task, assignment_task)
    voice_targets = build_voice_targets(_state_with_slides(state, slides), slide_count)
    voice_scripts = await _gather_voices(connector, brief, slide_count, voice_targets, personalization, reference_block)
    return ComponentBundle(
        slides=slides,
        quizzes=quizzes,
        note_blocks=note_blocks,
        assignment=assignment,
        voice_scripts=voice_scripts,
    )


async def _gather_voices(
    connector: AIConnector,
    brief: str,
    slide_count: int,
    voice_targets: list[VoiceTarget],
    personalization: PersonalizationArgs | None = None,
    reference_block: str = "",
) -> list:
    """슬라이드별 voice_script를 동시 생성한다(인덱스별 graceful 재시도).

    parse_voice는 (text, slide_idx)를 받으므로 partial로 slide_idx를 미리 바인딩한다.
    slide_idx를 바인딩해 두면 JSON 파싱 실패 시 raw 텍스트 폴백에서도 올바른 인덱스가 쓰인다.
    """
    prompt_personalization = personalization or _default_personalization_args()
    tasks = [
        _component(
            connector,
            pp.build_voice_request(
                brief,
                t.title,
                t.focus,
                t.summary,
                t.previous_title,
                t.slide_idx,
                slide_count,
                prompt_personalization,
                reference_block,
            ),
            partial(pp.parse_voice, slide_idx=t.slide_idx),
        )
        for t in voice_targets
    ]
    return list(await asyncio.gather(*tasks))


async def _component(
    connector: AIConnector,
    request: ChapterAIRequest,
    parse_fn: Callable[[str], _Result],
) -> _Result:
    """generate+파싱을 1회 재시도와 함께 수행한다(끝까지 실패하면 ConversionError)."""
    last_error: Exception | None = None
    for attempt in range(_RETRY_ATTEMPTS + 1):
        try:
            response = await connector.generate(request)
            return parse_fn(response.text)
        except (ConnectorError, ConversionError, ValidationError, ValueError, json.JSONDecodeError) as exc:
            # 커넥터 실패(timeout/auth 등)·파싱 실패만 잡아 항목별 재시도/에스컬레이션한다.
            # 예상 밖 예외(프로그래밍 오류)는 그대로 전파해 숨기지 않는다.
            last_error = exc
            schema = str(request.extra.get("schema", "?"))
            logger.warning(
                "parallel_generate: 컴포넌트({}) 생성 실패(시도 {}/{}): {}",
                schema,
                attempt + 1,
                _RETRY_ATTEMPTS + 1,
                exc,
            )
    schema = str(request.extra.get("schema", "?"))
    raise ConversionError(f"컴포넌트({schema}) 병렬 생성이 재시도 후에도 실패했다: {last_error}")


def _template_key(state: ChapterStudioState) -> str:
    value = state.get("template_key")
    if not isinstance(value, str) or value == "":
        raise ConversionError("template_key 문자열이 필요하다.")
    return value


def _resolve_slide_plan(
    state: ChapterStudioState, template_key: str, slide_count: int
) -> list[dict[str, object]]:
    """parse_slides에 넘길 slide_plan 행 목록을 확정한다(visual_type/must_have 포함).

    우선순위:
    1. state["slide_outline"] — context_node가 직렬화한 plan(visual_type 있음)을 그대로 사용.
       단, visual_type 키가 실제로 채워진 행들만 plan으로 인정한다(레거시 outline 방어).
    2. 누락/레거시면 build_slide_plan으로 결정적 재생성 후 직렬화한다(왕복 무결).

    이 함수가 직렬→역직렬 왕복 무결성을 보장한다: 반환 행은 slide_idx·visual_type·must_have를
    갖추어 _build_plan_map / _enforce_plan_visual_type / _relabel_chapter_title이 대조할 수 있다.
    """
    rows = state.get("slide_outline")
    if isinstance(rows, list):
        usable = [
            row
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("slide_idx"), int)
            and isinstance(row.get("visual_type"), str)
            and row.get("visual_type")
        ]
        # slide_count개 슬롯이 모두 visual_type을 갖춘 경우에만 신뢰한다.
        if len(usable) == slide_count:
            return usable
    # 폴백: state outline이 없거나 레거시면 plan을 결정적으로 재생성한다.
    plans = build_slide_plan(template_key, slide_count)
    return serialize_slide_plan(plans)


def _state_with_slides(state: ChapterStudioState, slides: list[GeneratedSlide]) -> ChapterStudioState:
    """voice target 생성 단계에서만 생성된 슬라이드 초안을 주입한다."""
    data = dict(state)
    data["slide_drafts"] = [slide.model_dump() for slide in slides]
    return cast(ChapterStudioState, data)


def _default_personalization_args() -> PersonalizationArgs:
    return PersonalizationArgs(
        weak_points="",
        audience_level="일반 학습자",
        tone=50,
        pace=50,
        tutor_depth=50,
        socratic=70,
        learning_goal="핵심 개념 이해와 실습",
    )


__all__ = ["generate_lesson_parallel"]
