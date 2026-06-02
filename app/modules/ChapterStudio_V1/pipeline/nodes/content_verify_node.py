from __future__ import annotations

from app.modules.ChapterStudio_V1.ai_connectors.registry import get_verifier_connector
from app.modules.ChapterStudio_V1.common.config import (
    lesson_content_verify_enabled,
    lesson_parallel_verify_enabled,
)
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.content_verify import verify_and_correct
from app.modules.ChapterStudio_V1.pipeline.content_verify_parallel import verify_and_correct_parallel
from app.modules.ChapterStudio_V1.pipeline.kanana_polish import inspect_and_polish_payload
from app.modules.ChapterStudio_V1.pipeline.payload import (
    GeneratedLessonPayload,
    payload_from_state_dict,
)
from app.modules.ChapterStudio_V1.pipeline.quiz_balance_pass import apply_quiz_balance_payload
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState
from app.modules.ChapterStudio_V1.pipeline.state_mapping import payload_to_state
from app.modules.ChapterStudio_V1.pipeline.voice_cohesion_pass import apply_voice_cohesion_payload


async def content_verify_node(state: ChapterStudioState) -> ChapterStudioState:
    """generate 노드가 stash한 payload의 사실·논리 오류를 검증·교정한다.

    형식 self-check/repair 다음 단계다. 기본은 병렬 검증·교정(슬라이드/퀴즈/음성 동시)이며,
    CHAPTERSTUDIO_PARALLEL_VERIFY=false면 직렬 경로로 폴백한다. 스위치가 꺼져 있거나 검증/교정이
    실패하면 원본 payload를 그대로 다운스트림 records로 펼친다(graceful). 다운스트림 records
    (slides·quiz_set·voice_scripts 등)는 이 노드가 단 한 번 emit한다.
    """
    payload = _load_payload(state)
    if lesson_content_verify_enabled():
        slide_count = _state_int(state, "slide_count")
        connector = get_verifier_connector()
        if lesson_parallel_verify_enabled():
            payload = await verify_and_correct_parallel(connector, payload, slide_count)
        else:
            payload = await verify_and_correct(connector, payload, slide_count)
    payload = await inspect_and_polish_payload(payload, tone_hint=_tone_hint(state))
    payload = await apply_voice_cohesion_payload(payload, topic=_topic_hint(state))
    payload = apply_quiz_balance_payload(payload, state)
    return payload_to_state(payload)


def _load_payload(state: ChapterStudioState) -> GeneratedLessonPayload:
    value = state.get("lesson_payload")
    if not isinstance(value, dict):
        raise ConversionError("lesson_payload dict가 필요하다.")
    return payload_from_state_dict(value)


def _state_int(state: ChapterStudioState, key: str) -> int:
    value = state.get(key)
    if not isinstance(value, int):
        raise ConversionError(f"{key} 정수가 필요하다.")
    return value


def _tone_hint(state: ChapterStudioState) -> str:
    formal = state.get("use_formal_speech")
    if formal is True:
        return "존댓말"
    if formal is False:
        return "반말"
    return ""


def _topic_hint(state: ChapterStudioState) -> str:
    for key in ("topic", "enriched_brief", "chapter_brief"):
        value = state.get(key)
        if isinstance(value, str) and value:
            return value
    return "강의 주제"


__all__ = ["content_verify_node"]
