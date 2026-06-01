from __future__ import annotations

from app.modules.ChapterStudio_V1.deploy.modal_app import (
    RESPONSE_SCHEMA,
    _select_guided_schema,
    assignment_schema,
    note_schema,
    quizzes_schema,
    response_schema,
    slides_schema,
    supporting_materials_schema,
    voice_script_schema,
    voice_segment_schema,
)


def test_default_modal_response_schema_preserves_five_slide_demo_contract() -> None:
    schema = RESPONSE_SCHEMA

    assert schema["properties"]["slides"]["minItems"] == 5
    assert schema["properties"]["slides"]["maxItems"] == 5
    assert schema["properties"]["voice_scripts"]["minItems"] == 5
    assert schema["properties"]["quizzes"]["minItems"] == 5


def test_modal_response_schema_supports_actual_lesson_slide_count() -> None:
    schema = response_schema(12)
    slides = schema["properties"]["slides"]
    voices = schema["properties"]["voice_scripts"]
    quizzes = schema["properties"]["quizzes"]

    assert slides["minItems"] == 12
    assert slides["maxItems"] == 12
    assert slides["items"]["properties"]["slide_idx"]["maximum"] == 11
    assert "table" in slides["items"]["properties"]["category"]["enum"]
    assert voices["minItems"] == 12
    assert voices["items"]["properties"]["slide_idx"]["maximum"] == 11
    assert voices["items"]["properties"]["script_text"]["maxLength"] == 2400
    assert quizzes["minItems"] == 12
    assert "slide_idx" in quizzes["items"]["required"]
    assert quizzes["items"]["properties"]["slide_idx"]["maximum"] == 11
    assert quizzes["items"]["properties"]["difficulty"]["enum"] == ["기억", "이해", "적용", "함정 교정", "실전 판단", "오해"]
    assert quizzes["items"]["properties"]["explanation"]["maxLength"] == 720
    assert schema["properties"]["note_blocks"]["minItems"] == 4
    assert schema["properties"]["note_blocks"]["items"]["properties"]["bullets"]["minItems"] == 3


def test_modal_voice_script_schema_supports_single_slide_retry() -> None:
    schema = voice_script_schema(15)

    assert schema["required"] == ["slide_idx", "script_text"]
    assert schema["properties"]["slide_idx"]["maximum"] == 14
    assert schema["properties"]["script_text"]["minLength"] == 850
    assert schema["properties"]["script_text"]["maxLength"] == 2400


def test_modal_voice_segment_schema_supports_parallel_segment_rewrite() -> None:
    schema = voice_segment_schema(15)

    assert schema["required"] == ["slide_idx", "segment_idx", "segment_text"]
    assert schema["properties"]["slide_idx"]["maximum"] == 14
    assert schema["properties"]["segment_idx"]["maximum"] == 3
    assert schema["properties"]["segment_text"]["minLength"] == 180
    assert schema["properties"]["segment_text"]["maxLength"] == 600


def test_modal_supporting_materials_schema_scopes_quizzes_and_assignment() -> None:
    schema = supporting_materials_schema(15)

    assert schema["required"] == ["quizzes", "assignment"]
    assert schema["properties"]["quizzes"]["minItems"] == 15
    assert "slide_idx" in schema["properties"]["quizzes"]["items"]["required"]
    assert schema["properties"]["assignment"]["required"] == ["title", "assignment_format", "expected_minutes", "steps", "rubric"]


def test_slides_schema_scopes_exactly_slide_count_slides() -> None:
    schema = slides_schema(10)
    item = schema["properties"]["slides"]["items"]

    assert schema["required"] == ["slides"]
    assert list(schema["properties"].keys()) == ["slides"]
    assert schema["properties"]["slides"]["minItems"] == 10
    assert schema["properties"]["slides"]["maxItems"] == 10
    assert item["properties"]["slide_idx"]["maximum"] == 9
    assert item["required"] == ["slide_idx", "title", "category", "narration", "visual", "checkpoint"]
    assert "html" not in item["properties"]
    assert "css" not in item["properties"]
    assert item["properties"]["visual"]["properties"]["type"]["enum"] == [
        "number_line",
        "comparison",
        "step_flow",
        "fraction_bar",
        "concept_map",
        "example_box",
    ]


def test_quizzes_schema_scopes_exactly_slide_count_quizzes() -> None:
    schema = quizzes_schema(12)

    assert schema["required"] == ["quizzes"]
    assert list(schema["properties"].keys()) == ["quizzes"]
    assert schema["properties"]["quizzes"]["minItems"] == 12
    assert schema["properties"]["quizzes"]["maxItems"] == 12


def test_note_schema_scopes_four_note_blocks_with_three_bullets() -> None:
    schema = note_schema(10)

    assert schema["required"] == ["note_blocks"]
    assert schema["properties"]["note_blocks"]["minItems"] == 4
    assert schema["properties"]["note_blocks"]["maxItems"] == 4
    assert schema["properties"]["note_blocks"]["items"]["properties"]["bullets"]["minItems"] == 3


def test_assignment_schema_forces_steps_and_rubric_as_arrays() -> None:
    schema = assignment_schema(10)

    assert schema["required"] == ["assignment"]
    assignment = schema["properties"]["assignment"]
    assert assignment["properties"]["steps"]["type"] == "array"
    assert assignment["properties"]["rubric"]["type"] == "array"
    assert assignment["properties"]["rubric"]["items"]["type"] == "string"


def test_select_guided_schema_routes_each_kind() -> None:
    assert "slides" in _select_guided_schema("slides", 10)["properties"]
    assert "quizzes" in _select_guided_schema("quizzes", 10)["properties"]
    assert "note_blocks" in _select_guided_schema("note", 10)["properties"]
    assert "assignment" in _select_guided_schema("assignment", 10)["properties"]
    assert _select_guided_schema("voice_script", 10)["required"] == ["slide_idx", "script_text"]
    # 미지정/lesson은 전체 lesson 스키마로 폴백한다(기존 호환).
    assert "slides" in _select_guided_schema("lesson", 10)["properties"]
    assert "quizzes" in _select_guided_schema("unknown_kind", 10)["properties"]
