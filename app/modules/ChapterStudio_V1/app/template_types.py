from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

SlideCategory = Literal["text", "diagram", "code", "math", "chart", "interactive"]


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
