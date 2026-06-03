from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

SlideCategory = Literal["text", "diagram", "code", "math", "chart", "interactive"]

# 슬라이드별 허용 visual.type 완전 목록 — AI가 이 범위 밖의 type을 반환하면 거부한다.
VisualType = Literal[
    "number_line",
    "comparison",
    "comparison-table",
    "step_flow",
    "flow-strip",
    "fraction_bar",
    "concept_map",
    "example_box",
    "metric-card",
]

# text category 전용 허용 visual.type 집합
TEXT_CATEGORY_VISUAL_TYPES: frozenset[str] = frozenset(
    {"metric-card", "comparison-table", "example_box"}
)

# visual.type → 정규화된 표준 키 매핑 (하이픈/언더스코어 혼용 정규화)
VISUAL_TYPE_ALIASES: dict[str, str] = {
    "comparison_table": "comparison-table",
    "flow_strip": "flow-strip",
    "metric_card": "metric-card",
    "example-box": "example_box",
}


class TemplateOption(TypedDict):
    value: str
    label: str


class TemplateVisualOption(TypedDict):
    value: str
    title_color: str
    concept_bg: str
    practice_bg: str
    caution_bg: str
    list_style: str
    section_rule: str


@dataclass(frozen=True)
class SlideFrame:
    slide_idx: int
    category: SlideCategory
    role: str
    must_have: tuple[str, ...]
    # 이 프레임에서 AI가 생성해야 하는 visual.type — plan-first로 결정된다.
    # None이면 category 기본 규칙(TEXT_CATEGORY_VISUAL_TYPES 등)에 따른다.
    visual_type: str | None = None


@dataclass(frozen=True)
class StudyTemplate:
    key: str
    label: str
    intent: str
    contract: str
    frames: tuple[SlideFrame, ...]
    note_blocks: tuple[str, ...]
    quiz_mix: tuple[str, ...]


@dataclass(frozen=True)
class TemplateVisual:
    title_color: str
    concept_bg: str
    practice_bg: str
    caution_bg: str
    list_style: str
    section_rule: str
