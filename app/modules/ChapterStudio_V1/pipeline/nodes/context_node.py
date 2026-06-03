from __future__ import annotations

from app.modules.ChapterStudio_V1.app.study_templates import get_template, select_template, select_template_decision
from app.modules.ChapterStudio_V1.pipeline.slide_plan import build_slide_plan, serialize_slide_plan
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState


def prepare_context_node(state: ChapterStudioState) -> ChapterStudioState:
    """요청 주제를 템플릿과 슬라이드 계획 목록으로 확정한다."""
    topic = _state_text(state, "topic")
    brief = _state_text(state, "chapter_brief")
    slide_count = _state_int(state, "slide_count")
    requested_template = _optional_text(state, "requested_template", "auto")
    decision_text = f"{topic}\n{brief}\n{_optional_text(state, 'learning_goal', '')}"
    if requested_template == "auto":
        decision = select_template_decision(decision_text)
        template = get_template(decision.key)
        reason = decision.reason
    else:
        template = select_template(requested_template, decision_text)
        reason = f"사용자 지정 템플릿: {requested_template}"
    slide_plans = build_slide_plan(template.key, slide_count)
    return {
        "template_key": template.key,
        "enriched_brief": _enriched_brief(state, template.key, reason),
        # slide_outline을 SlidePlan 직렬화로 교체한다 — visual_type이 포함된다.
        # serialize_slide_plan이 state 저장 형식과 parse_slides 소비 형식의 단일 진실 소스다.
        "slide_outline": serialize_slide_plan(slide_plans),
    }


def _state_text(state: ChapterStudioState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{key} 문자열이 필요하다.")
    return value


def _optional_text(state: ChapterStudioState, key: str, default: str) -> str:
    value = state.get(key)
    if isinstance(value, str):
        return value
    return default


def _state_int(state: ChapterStudioState, key: str) -> int:
    value = state.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} 정수가 필요하다.")
    return value


def _enriched_brief(state: ChapterStudioState, template_key: str, reason: str) -> str:
    return "\n".join(
        [
            f"주제: {_state_text(state, 'topic')}",
            f"챕터 개요: {_state_text(state, 'chapter_brief')}",
            f"학습 목표: {_optional_text(state, 'learning_goal', '핵심 개념 이해와 실습')}",
            f"대상 수준: {_optional_text(state, 'audience_level', '일반 학습자')}",
            f"취약점: {_optional_text(state, 'weak_points', '요청에 명시된 약점 없음') or '요청에 명시된 약점 없음'}",
            f"템플릿: {template_key}",
            f"템플릿 근거: {reason}",
        ]
    )


__all__ = ["prepare_context_node"]
