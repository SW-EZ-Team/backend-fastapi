from __future__ import annotations

from typing import NotRequired, TypedDict


class DemoSlide(TypedDict):
    slide_idx: int
    title: str
    focus: str
    checkpoint: str
    category: str
    template_role: str
    iframe_html: str


class DemoQuiz(TypedDict):
    question: str
    choices: list[str]
    answer_idx: int
    difficulty: str
    explanation: str


class DemoNoteBlock(TypedDict):
    heading: str
    bullets: list[str]


class DemoAssignment(TypedDict):
    title: str
    assignment_format: str
    expected_minutes: int
    steps: list[str]
    rubric: list[str]


class DemoVoiceScript(TypedDict):
    slide_idx: int
    script_text: str


class DemoStoragePreview(TypedDict):
    table: str
    rows: int
    note: str


class DemoAgentToolUse(TypedDict):
    stage: str
    tool: str
    reason: str
    output: str


class DemoTimeoutPolicy(TypedDict):
    engine: str
    limit_sec: int
    policy: str


class DemoResult(TypedDict):
    topic: str
    template_label: str
    quality_marks: list[str]
    slides: list[DemoSlide]
    quizzes: list[DemoQuiz]
    note_blocks: list[DemoNoteBlock]
    assignment: DemoAssignment
    voice_scripts: list[DemoVoiceScript]
    storage_preview: list[DemoStoragePreview]
    agent_plan: NotRequired[list[DemoAgentToolUse]]
    timeout_policy: NotRequired[DemoTimeoutPolicy]
