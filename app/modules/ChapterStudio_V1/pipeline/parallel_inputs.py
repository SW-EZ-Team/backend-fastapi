"""컴포넌트 병렬 생성 입력 추출.

LangGraph 상태(prepare_context가 채운 enriched_brief·slide_outline 등)에서 컴포넌트
프롬프트에 넣을 공통 brief 문자열, 슬라이드 역할 아웃라인 텍스트, 슬라이드별 voice 타깃을
뽑는 순수 함수만 둔다. LLM을 호출하지 않는다.

공개 API:
    - build_brief(state)                     : 컴포넌트 공통 강의 요청 brief
    - build_outline_text(state, slide_count) : 슬라이드 역할 아웃라인 텍스트
    - build_voice_targets(state, slide_count): 슬라이드별 voice 생성 타깃
"""
from __future__ import annotations

from dataclasses import dataclass

from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState


@dataclass(frozen=True)
class VoiceTarget:
    """슬라이드 1개의 voice_script 생성에 필요한 최소 컨텍스트."""

    slide_idx: int
    title: str
    focus: str
    summary: str


@dataclass(frozen=True)
class PersonalizationArgs:
    """컴포넌트 프롬프트에 공통 전달할 개인화 인자."""

    weak_points: str
    audience_level: str
    tone: int
    pace: int
    tutor_depth: int
    socratic: int
    learning_goal: str


def build_brief(state: ChapterStudioState) -> str:
    """모든 컴포넌트 프롬프트가 공유할 강의 요청 brief를 만든다."""
    return _state_text(state, "enriched_brief")


def build_outline_text(state: ChapterStudioState, slide_count: int) -> str:
    """확정 슬라이드 역할(slide_outline)을 한 줄씩 텍스트로 펼친다."""
    rows = _outline_rows(state)
    if not rows:
        return f"슬라이드 역할 목록 없음(슬라이드 수 {slide_count})"
    lines: list[str] = []
    for row in rows:
        must_have = row.get("must_have")
        joined = ", ".join(str(item) for item in must_have) if isinstance(must_have, list) else ""
        lines.append(
            f"slide {row.get('slide_idx')}: category={row.get('category')}, "
            f"role={row.get('role')}, must_have={joined}"
        )
    return "\n".join(lines)


def build_voice_targets(state: ChapterStudioState, slide_count: int) -> list[VoiceTarget]:
    """슬라이드별 voice 타깃을 0..slide_count-1 완전집합으로 만든다(아웃라인 컨텍스트 활용)."""
    by_idx = _outline_by_idx(state)
    targets: list[VoiceTarget] = []
    for idx in range(slide_count):
        row = by_idx.get(idx, {})
        role = _as_text(row.get("role")) or "핵심 개념 설명"
        category = _as_text(row.get("category")) or "text"
        targets.append(
            VoiceTarget(
                slide_idx=idx,
                title=role,
                focus=role,
                summary=f"category={category}, 역할={role}",
            )
        )
    return targets


def build_personalization_args(state: ChapterStudioState) -> PersonalizationArgs:
    """state의 개인화 키를 병렬 프롬프트 인자로 정규화한다."""
    return PersonalizationArgs(
        weak_points=_optional_state_text(state, "weak_points"),
        audience_level=_optional_state_text(state, "audience_level") or "일반 학습자",
        tone=_state_int_default(state, "tone", 50),
        pace=_state_int_default(state, "pace", 50),
        tutor_depth=_state_int_default(state, "tutor_depth", 50),
        socratic=_state_int_default(state, "socratic", 70),
        learning_goal=_optional_state_text(state, "learning_goal") or "핵심 개념 이해와 실습",
    )


def _outline_rows(state: ChapterStudioState) -> list[dict[str, object]]:
    value = state.get("slide_outline")
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _outline_by_idx(state: ChapterStudioState) -> dict[int, dict[str, object]]:
    result: dict[int, dict[str, object]] = {}
    for row in _outline_rows(state):
        idx = row.get("slide_idx")
        if isinstance(idx, int):
            result[idx] = row
    return result


def _as_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_state_text(state: ChapterStudioState, key: str) -> str:
    value = state.get(key)
    return value if isinstance(value, str) else ""


def _state_int_default(state: ChapterStudioState, key: str, default: int) -> int:
    value = state.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _state_text(state: ChapterStudioState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or value == "":
        raise ConversionError(f"{key} 문자열이 필요하다.")
    return value


__all__ = ["PersonalizationArgs", "VoiceTarget", "build_brief", "build_outline_text", "build_personalization_args", "build_voice_targets"]
