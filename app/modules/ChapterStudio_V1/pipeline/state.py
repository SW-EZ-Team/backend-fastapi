from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

StateRecord = dict[str, object]
StateRecords = list[StateRecord]


class ChapterStudioState(TypedDict, total=False):
    user_id: str
    curriculum_id: str
    topic: str
    source_mode: str
    pdf_file_name: str
    duration_days: int
    depth: str
    teacher: str
    tone: int
    pace: int
    tutor_depth: int
    socratic: int
    audience_level: str
    learning_goal: str
    chapter_brief: str
    slide_count: int
    requested_template: str
    template_key: str
    generation_model: str
    enriched_brief: str
    weak_points: str
    reference_context_prompt: str
    slide_outline: StateRecords
    slide_drafts: StateRecords
    slides: Annotated[StateRecords, add]
    quiz_set: StateRecords
    core_note: str
    assignment_seed: str
    assignment_meta: StateRecord
    voice_scripts: Annotated[StateRecords, add]
    voice_audio_files: Annotated[StateRecords, add]


def append_records(left: StateRecords, right: StateRecords) -> StateRecords:
    """LangGraph add reducer와 같은 방식으로 결과 목록을 누적한다."""
    return left + right
