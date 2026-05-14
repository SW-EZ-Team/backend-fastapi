from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.app.demo_pipeline import build_demo_result, demo_steps
from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext, ReferenceBookHit


def test_demo_steps_contains_pipeline_nodes() -> None:
    assert "후처리·보안 렌더" in demo_steps()
    assert "Codex CLI 도구 실행" in demo_steps("codex_cli")


@pytest.mark.asyncio
async def test_demo_result_contains_all_outputs() -> None:
    result = await build_demo_result(_input("테스트 주제"), 5)
    assert len(result["slides"]) == 5
    assert len(result["quizzes"]) == 5
    assert result["note_blocks"]
    assert result["assignment"]["assignment_format"]
    assert result["assignment"]["expected_minutes"] == 20
    assert result["assignment"]["steps"]
    assert len(result["voice_scripts"]) == 5


@pytest.mark.asyncio
async def test_demo_result_exposes_srcdoc_for_frontend_iframe() -> None:
    result = await build_demo_result(_input("끼워넣기 검증"), 5)
    iframe_html = result["slides"][0]["iframe_html"]
    assert iframe_html.lstrip().startswith("<!DOCTYPE html>")
    assert not iframe_html.lstrip().startswith("<iframe")
    assert 'sandbox="' not in iframe_html


@pytest.mark.asyncio
async def test_demo_result_preserves_chart_iframe() -> None:
    result = await build_demo_result(_input("차트 주제"), 5, "visual_map")
    assert "data:image/png;base64," in result["slides"][1]["iframe_html"]


@pytest.mark.asyncio
async def test_demo_chart_explains_color_semantics() -> None:
    result = await build_demo_result(_input("p-value와 신뢰구간"), 5, "auto")
    iframe = result["slides"][0]["iframe_html"]
    assert "chart-legend" in iframe
    assert "변수 구조" in iframe
    assert "추론 근거" in iframe
    assert "해석 한계" in iframe
    assert "--chart-0:#2A3B45" in iframe


@pytest.mark.asyncio
async def test_demo_result_exposes_template_quality_and_storage() -> None:
    result = await build_demo_result(_input("시험 대비"), 5, "exam_focus")
    assert result["template_label"] == "시험 대비"
    assert len(result["quality_marks"]) >= 4
    assert any(mark.startswith("시각:") for mark in result["quality_marks"])
    assert result["storage_preview"][0]["table"] == "chapter_studio.slide"
    assert "과제 형식" in result["storage_preview"][3]["note"]


@pytest.mark.asyncio
async def test_demo_result_applies_visual_theme_to_iframe_css() -> None:
    result = await build_demo_result(_input("통계학자 로널드 피셔"), 5, "auto")
    assert result["template_label"] == "인물 탐구"
    assert "#2A3B45" in result["slides"][0]["iframe_html"]
    assert "생애 맥락" in result["slides"][0]["iframe_html"]


@pytest.mark.asyncio
async def test_demo_result_marks_semantic_importance() -> None:
    result = await build_demo_result(_input("분산 분석"), 5, "foundation_overview")
    first_slide = result["slides"][0]["iframe_html"]
    assert "tag-def" in first_slide
    assert "tag-context" in first_slide
    assert "tag-warning" in first_slide
    assert "왜 이 주제인가" in first_slide


@pytest.mark.asyncio
async def test_demo_result_uses_readable_korean_particles() -> None:
    result = await build_demo_result(_input("로널드 피셔"), 5, "person_profile")
    assert "로널드 피셔는" in result["slides"][0]["iframe_html"]
    assert "로널드 피셔를" in result["slides"][2]["iframe_html"]


@pytest.mark.asyncio
async def test_demo_result_injects_reference_book_into_notes_assignment_and_voice() -> None:
    result = await build_demo_result(_input_with_reference("회귀분석"), 5, "statistics_inference")

    note_text = "\n".join(bullet for block in result["note_blocks"] for bullet in block["bullets"])
    voice_text = "\n".join(item["script_text"] for item in result["voice_scripts"])
    assignment_text = "\n".join(result["assignment"]["steps"])

    assert "p.88" in note_text
    assert "p.88" in voice_text
    assert "p.88" in assignment_text


def _input(topic: str) -> DemoGenerationInput:
    return DemoGenerationInput(topic=topic, duration_days=60, teacher="cat", audience_level="초급")


def _input_with_reference(topic: str) -> DemoGenerationInput:
    return DemoGenerationInput(
        topic=topic,
        duration_days=60,
        teacher="cat",
        audience_level="초급",
        reference_book_context=ReferenceBookContext(
            source_title="회귀 교재",
            query=topic,
            page_count=120,
            hits=[
                ReferenceBookHit(
                    page=88,
                    snippet="회귀분석에서 잔차는 관측값과 예측값의 차이를 뜻한다.",
                    score=5.0,
                    source_title="회귀 교재",
                )
            ],
        ),
    )
