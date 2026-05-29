from __future__ import annotations

from operator import add
from typing import Annotated, get_args, get_origin, get_type_hints

from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState, append_records


def test_state_has_phase2_fields() -> None:
    hints = get_type_hints(ChapterStudioState, include_extras=True)

    assert set(hints) == {
        "user_id",
        "curriculum_id",
        "topic",
        "source_mode",
        "pdf_file_name",
        "duration_days",
        "depth",
        "teacher",
        "tone",
        "pace",
        "tutor_depth",
        "socratic",
        "audience_level",
        "learning_goal",
        "chapter_brief",
        "slide_count",
        "requested_template",
        "template_key",
        "generation_model",
        "enriched_brief",
        "weak_points",
        "reference_context_prompt",
        "slide_outline",
        "slide_drafts",
        "slides",
        "quiz_set",
        "core_note",
        "assignment_seed",
        "assignment_meta",
        "voice_scripts",
        "voice_audio_files",
    }


def test_state_reducer_annotations_use_add() -> None:
    hints = get_type_hints(ChapterStudioState, include_extras=True)

    assert get_origin(hints["slides"]) is Annotated
    assert get_args(hints["slides"])[1] is add
    assert get_args(hints["voice_scripts"])[1] is add
    assert get_args(hints["voice_audio_files"])[1] is add


def test_append_records_accumulates() -> None:
    result = append_records([{"slide_idx": 0}], [{"slide_idx": 1}])

    assert result == [{"slide_idx": 0}, {"slide_idx": 1}]
