from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput, prompt_context
from app.modules.ChapterStudio_V1.app.frontend_contract import contract
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext, ReferenceBookHit


def test_frontend_contract_contains_course_explore_inputs() -> None:
    data = contract()
    fields = data["accepted_fields"]
    assert "source_mode" in fields
    assert "duration_days" in fields
    assert "teacher" in fields
    assert "socratic" in fields
    assert len(data["templates"]) >= 20
    assert len(data["template_visuals"]) >= 40
    assert {"value": "chem_reaction", "label": "화학 반응"} in data["templates"]
    assert {"value": "clinical_reasoning", "label": "의과 추론"} in data["templates"]
    assert any(item["value"] == "statistics_inference" for item in data["template_visuals"])
    assert "lesson_id로 infra DB" in data["db_input_policy"]
    assert any(item["key"] == "slide_count" for item in data["db_required_fields"])
    assert data["chat_stream_path"].endswith("/chat/stream")
    assert "slideIdx" in data["chat_required_fields"]


def test_prompt_context_reflects_frontend_inputs() -> None:
    data = DemoGenerationInput(
        topic="Rust 소유권",
        source_mode="pdf",
        pdf_file_name="rust.pdf",
        duration_days=14,
        depth="deep",
        teacher="fox",
        weak_points="라이프타임",
    )
    context = prompt_context(data)
    assert "PDF 업로드" in context
    assert "14일" in context
    assert "여우 선배" in context
    assert "라이프타임" in context


def test_prompt_context_reflects_reference_book_context() -> None:
    data = DemoGenerationInput(
        topic="p-value",
        reference_book_context=ReferenceBookContext(
            source_title="통계 교재",
            query="p-value",
            page_count=100,
            hits=[
                ReferenceBookHit(
                    page=42,
                    snippet="p-value는 귀무가설 아래 확률이다.",
                    score=3.0,
                    source_title="통계 교재",
                )
            ],
        ),
    )
    context = prompt_context(data)

    assert "참고도서" in context
    assert "p.42" in context


def test_invalid_teacher_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DemoGenerationInput(topic="테스트", teacher="dragon")
