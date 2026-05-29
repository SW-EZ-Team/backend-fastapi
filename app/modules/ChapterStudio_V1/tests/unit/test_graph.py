from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.ai_connectors import registry
from app.modules.ChapterStudio_V1.app.generation_context import GenerationInput
from app.modules.ChapterStudio_V1.pipeline.graph import generate_chapter_response, get_compiled_graph


class FakeTextConnector:
    name = "unit_fake"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        assert "확정 슬라이드 역할:" in req.user
        assert "slide 9:" in req.user
        return ChapterAIResponse(
            text=json.dumps(_payload(int(req.extra["slide_count"])), ensure_ascii=False),
            model=self.name,
            input_tokens=1,
            output_tokens=1,
            finish_reason="stop",
        )

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return feature == "json_mode"


@pytest.fixture(autouse=True)
def fake_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    registry.clear_cache()
    get_compiled_graph.cache_clear()
    monkeypatch.setitem(registry._REGISTRY, "unit_fake", FakeTextConnector)
    monkeypatch.setenv("ACTIVE_TEXT_MODEL", "unit_fake")
    yield
    registry.clear_cache()
    get_compiled_graph.cache_clear()


@pytest.mark.anyio
async def test_graph_generates_response() -> None:
    request = GenerationInput(topic="정렬 알고리즘", chapter_brief="정렬 알고리즘", slide_count=10)

    response = await generate_chapter_response(request, "chapter-test")

    assert response.chapter_id == "chapter-test"
    assert len(response.slides) == 10
    assert len(response.quizzes) == 10
    assert response.note.content.startswith("## 핵심")
    assert response.assignment.content.startswith("실습 과제")


def _payload(slide_count: int) -> dict[str, object]:
    return {
        "slides": [_slide(idx) for idx in range(slide_count)],
        "quizzes": [_quiz(idx) for idx in range(slide_count)],
        "note_blocks": [{"heading": "핵심", "bullets": ["핵심을 짧게 복습합니다."]}],
        "assignment": {
            "title": "실습 과제",
            "assignment_format": "서술형",
            "expected_minutes": 20,
            "steps": ["개념을 설명합니다."],
            "rubric": ["근거를 확인합니다."],
        },
        "voice_scripts": [{"slide_idx": idx, "script_text": "설명 대본입니다."} for idx in range(slide_count)],
    }


def _slide(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "title": f"슬라이드 {idx}",
        "focus": "핵심 흐름",
        "checkpoint": "자가점검",
        "category": "text",
        "html": "<section><h2>핵심</h2><p>설명 문장입니다.</p></section>",
        "css": "",
    }


def _quiz(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "question": "질문입니다.",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "이해",
        "explanation": "해설입니다.",
    }
