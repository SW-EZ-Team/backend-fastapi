from __future__ import annotations

from typing import Literal, TypedDict

from app.modules.ChapterStudio_V1.app.study_templates import template_options, visual_options
from app.modules.ChapterStudio_V1.app.template_types import TemplateVisualOption

SourceMode = Literal["topic", "pdf"]
DepthLevel = Literal["basic", "normal", "deep"]
TeacherId = Literal["owl", "cat", "fox", "bear"]


class OptionItem(TypedDict):
    value: str
    label: str


class DbInputField(TypedDict):
    key: str
    source: str
    required: bool


class FrontendContract(TypedDict):
    source_modes: list[OptionItem]
    duration_days: list[int]
    depth_levels: list[OptionItem]
    teachers: list[OptionItem]
    templates: list[OptionItem]
    template_visuals: list[TemplateVisualOption]
    tutor_sliders: list[str]
    accepted_fields: list[str]
    db_input_policy: str
    db_required_fields: list[DbInputField]
    chat_stream_path: str
    chat_required_fields: list[str]
    curriculum_create_path: str
    curriculum_preview_path: str
    curriculum_role_policy: str


SOURCE_MODES: list[OptionItem] = [
    {"value": "topic", "label": "주제로 시작하기"},
    {"value": "pdf", "label": "PDF로 시작하기"},
]
DURATION_DAYS = [14, 30, 60, 90]
DEPTH_LEVELS: list[OptionItem] = [
    {"value": "basic", "label": "기초 중심"},
    {"value": "normal", "label": "표준"},
    {"value": "deep", "label": "심화·예외까지"},
]
TEACHERS: list[OptionItem] = [
    {"value": "owl", "label": "올빼미 교수 · 차분·소크라테스"},
    {"value": "cat", "label": "냥 튜터 · 친근·비유"},
    {"value": "fox", "label": "여우 선배 · 똑똑·장난기"},
    {"value": "bear", "label": "곰 코치 · 듬직·반복"},
]
TUTOR_SLIDERS = ["tone", "pace", "tutor_depth", "socratic"]
ACCEPTED_FIELDS = [
    "source_mode", "topic", "pdf_file_name", "duration_days", "depth",
    "teacher", "tone", "pace", "tutor_depth", "socratic", "audience_level",
    "learning_goal", "weak_points", "chapter_title", "chapter_brief",
    "reference_book_context",
]
DB_INPUT_POLICY = "데모는 mock 입력을 쓰지만 운영 FastAPI는 lesson_id로 infra DB의 generation_context를 읽는다."
CHAT_STREAM_PATH = "/tutoring/{tutoringId}/lessons/{lessonId}/chat/stream"
CHAT_REQUIRED_FIELDS = ["lessonId", "slideId", "slideIdx", "message", "selectedText", "playbackSec"]
CURRICULUM_CREATE_PATH = "/tutoring"
CURRICULUM_PREVIEW_PATH = "/tutoring/{id}/curriculum"
CURRICULUM_ROLE_POLICY = "커리큘럼 생성은 별도 CourseDetail 흐름이며 Planner(Opus)가 담당한다."
DB_REQUIRED_FIELDS: list[DbInputField] = [
    {"key": "lesson_id", "source": "chapter_studio.curriculum_unit.lesson_id", "required": True},
    {"key": "topic", "source": "chapter_studio.curriculum_unit.title", "required": True},
    {"key": "chapter_brief", "source": "chapter_studio.curriculum_unit.summary", "required": True},
    {"key": "learning_goal", "source": "chapter_studio.curriculum_unit.learning_goal", "required": False},
    {"key": "slide_count", "source": "chapter_studio.curriculum_unit.slide_count", "required": True},
    {"key": "source_mode", "source": "chapter_studio.curriculum_plan.source_type", "required": True},
    {"key": "pdf_file_name", "source": "chapter_studio.curriculum_plan.source_ref", "required": False},
    {"key": "duration_days", "source": "lesson_generation_status.generation_context", "required": False},
    {"key": "teacher", "source": "lesson_generation_status.generation_context", "required": False},
    {"key": "tone/pace/depth/socratic", "source": "lesson_generation_status.generation_context", "required": False},
    {"key": "audience_level", "source": "lesson_generation_status.generation_context", "required": False},
    {"key": "weak_points", "source": "lesson_generation_status.generation_context", "required": False},
    {"key": "reference_book_context", "source": "lesson_generation_status.generation_context", "required": False},
    {"key": "chapter_title", "source": "chapter_studio.curriculum_unit.title", "required": True},
    {"key": "template", "source": "lesson_generation_status.requested_template", "required": False},
]


def contract() -> FrontendContract:
    """프론트 초안과 맞춘 입력 필드 계약을 반환한다."""
    return {
        "source_modes": SOURCE_MODES,
        "duration_days": DURATION_DAYS,
        "depth_levels": DEPTH_LEVELS,
        "teachers": TEACHERS,
        "templates": template_options(),
        "template_visuals": visual_options(),
        "tutor_sliders": TUTOR_SLIDERS,
        "accepted_fields": ACCEPTED_FIELDS,
        "db_input_policy": DB_INPUT_POLICY,
        "db_required_fields": DB_REQUIRED_FIELDS,
        "chat_stream_path": CHAT_STREAM_PATH,
        "chat_required_fields": CHAT_REQUIRED_FIELDS,
        "curriculum_create_path": CURRICULUM_CREATE_PATH,
        "curriculum_preview_path": CURRICULUM_PREVIEW_PATH,
        "curriculum_role_policy": CURRICULUM_ROLE_POLICY,
    }


def teacher_label(teacher: str) -> str:
    """튜터 id를 생성 프롬프트에 넣을 설명으로 바꾼다."""
    for item in TEACHERS:
        if item["value"] == teacher:
            return item["label"]
    return TEACHERS[0]["label"]


def depth_label(depth: str) -> str:
    """난이도 id를 생성 프롬프트에 넣을 설명으로 바꾼다."""
    for item in DEPTH_LEVELS:
        if item["value"] == depth:
            return item["label"]
    return DEPTH_LEVELS[1]["label"]
