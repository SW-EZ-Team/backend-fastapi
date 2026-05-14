from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

StateRecord = dict[str, object]
StateRecords = list[StateRecord]


class ChapterStudioState(TypedDict, total=False):
    user_id: str
    curriculum_id: str
    chapter_brief: str
    enriched_brief: str
    weak_points: str
    slide_outline: StateRecords
    slides: Annotated[StateRecords, add]
    quiz_set: StateRecords
    core_note: str
    assignment_seed: str
    voice_scripts: Annotated[StateRecords, add]
    voice_audio_files: Annotated[StateRecords, add]


def append_records(left: StateRecords, right: StateRecords) -> StateRecords:
    """LangGraph add reducer와 같은 방식으로 결과 목록을 누적한다."""
    return left + right
