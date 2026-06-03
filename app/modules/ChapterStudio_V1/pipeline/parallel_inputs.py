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
from typing import Literal

from app.modules.ChapterStudio_V1.common.config import (
    VOICE_SECTION_INSTRUCTIONS,
    VOICE_SECTION_RANGES,
)
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState
from app.modules.ChapterStudio_V1.pipeline.voice_target_context import (
    draft_by_idx,
    first_text,
    previous_title,
    voice_summary,
)

VoiceIntroMode = Literal["greeting", "bridge"]


@dataclass(frozen=True)
class VoiceSectionBlueprint:
    """섹션 슬롯 1개의 결정적 메타데이터 — AI가 text만 채운다."""

    role: str                     # intro / core / example / closing
    min_chars: int                # 최소 문자 수 (결정적 상수)
    max_chars: int                # 최대 문자 수 (결정적 상수)
    instruction: str              # 내용 지시 (코드 상수)
    intro_mode: VoiceIntroMode | None = None  # intro 슬롯에만 설정


@dataclass(frozen=True)
class VoiceBlueprint:
    """슬라이드 1개의 섹션 블루프린트 전체 — 코드가 섹션 수·순서·길이를 결정한다."""

    slide_idx: int
    intro_mode: VoiceIntroMode    # greeting(slide_idx=0) / bridge(나머지)
    sections: tuple[VoiceSectionBlueprint, ...]


def _intro_instruction(intro_mode: VoiceIntroMode, previous_title: str) -> str:
    """intro 슬롯 지시를 모드·직전 제목으로 구체화한다(레거시 _voice_intro_rule 품질 복원).

    bridge 모드일 때 직전 화면 제목이 있으면 그 제목을 명시해 도입이 실제로 직전 내용을
    잇게 한다. 제목이 없으면 일반 bridge 지시로 폴백한다.
    """
    base = VOICE_SECTION_INSTRUCTIONS["intro"]
    if intro_mode == "greeting":
        return base
    if previous_title:
        return (
            f"{base} 직전 화면 '{previous_title}'에서 자연스럽게 이어지는 한 문장으로 시작한다."
        )
    return base


def build_voice_blueprint(slide_idx: int, previous_title: str) -> VoiceBlueprint:
    """슬라이드 인덱스·직전 제목으로부터 결정적 섹션 블루프린트를 만든다(AI 미관여).

    섹션 개수·role·순서·길이 범위는 VOICE_SECTION_RANGES 상수에서 읽고,
    intro 모드는 slide_idx로 결정한다. bridge intro는 previous_title을 지시에 포함한다.
    """
    # slide_idx==0이면 greeting(인사 허용), 그 외는 bridge(직전 연결 강제).
    intro_mode: VoiceIntroMode = "greeting" if slide_idx == 0 else "bridge"
    roles = ("intro", "core", "example", "closing")
    blueprints: list[VoiceSectionBlueprint] = []
    for role in roles:
        min_c, max_c = VOICE_SECTION_RANGES[role]
        # intro 슬롯에만 모드·직전 제목을 반영한 구체 지시를 넣는다.
        if role == "intro":
            blueprints.append(
                VoiceSectionBlueprint(
                    role=role,
                    min_chars=min_c,
                    max_chars=max_c,
                    instruction=_intro_instruction(intro_mode, previous_title),
                    intro_mode=intro_mode,
                )
            )
        else:
            blueprints.append(
                VoiceSectionBlueprint(
                    role=role,
                    min_chars=min_c,
                    max_chars=max_c,
                    instruction=VOICE_SECTION_INSTRUCTIONS[role],
                )
            )
    return VoiceBlueprint(
        slide_idx=slide_idx,
        intro_mode=intro_mode,
        sections=tuple(blueprints),
    )


@dataclass(frozen=True)
class VoiceTarget:
    """슬라이드 1개의 voice_script 생성에 필요한 최소 컨텍스트."""

    slide_idx: int
    title: str
    focus: str
    summary: str
    previous_title: str = ""


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
    use_formal_speech: bool = True
    use_emoji: bool = False
    tutor_name: str = ""
    tutor_tagline: str = ""
    is_default_tutor: bool = True
    voice_sample_url: str = ""


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
    """슬라이드별 voice 타깃을 0..slide_count-1 완전집합으로 만든다(화면 내용 우선)."""
    by_idx = _outline_by_idx(state)
    drafts = draft_by_idx(state)
    targets: list[VoiceTarget] = []
    for idx in range(slide_count):
        row = by_idx.get(idx, {})
        draft = drafts.get(idx, {})
        role = _as_text(row.get("role")) or "핵심 개념 설명"
        category = _as_text(row.get("category")) or "text"
        title = first_text(draft.get("title"), row.get("title"), role)
        focus = first_text(draft.get("focus"), draft.get("narration"), row.get("focus"), role)
        targets.append(
            VoiceTarget(
                slide_idx=idx,
                title=title,
                focus=focus,
                summary=voice_summary(draft, row, category, role),
                previous_title=previous_title(idx, drafts, by_idx),
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
        use_formal_speech=_state_bool_default(state, "use_formal_speech", True),
        use_emoji=_state_bool_default(state, "use_emoji", False),
        tutor_name=_optional_state_text(state, "tutor_name"),
        tutor_tagline=_optional_state_text(state, "tutor_tagline"),
        is_default_tutor=_state_bool_default(state, "is_default_tutor", True),
        voice_sample_url=_optional_state_text(state, "voice_sample_url"),
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


def _state_bool_default(state: ChapterStudioState, key: str, default: bool) -> bool:
    value = state.get(key)
    return value if isinstance(value, bool) else default


def _state_text(state: ChapterStudioState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or value == "":
        raise ConversionError(f"{key} 문자열이 필요하다.")
    return value


__all__ = [
    "PersonalizationArgs",
    "VoiceBlueprint",
    "VoiceIntroMode",
    "VoiceSectionBlueprint",
    "VoiceTarget",
    "build_brief",
    "build_outline_text",
    "build_personalization_args",
    "build_voice_blueprint",
    "build_voice_targets",
]
