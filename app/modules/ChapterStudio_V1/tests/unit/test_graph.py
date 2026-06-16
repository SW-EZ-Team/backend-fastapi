from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.ai_connectors import registry
from app.modules.ChapterStudio_V1.app.generation_context import GenerationInput
from app.modules.ChapterStudio_V1.pipeline.graph import generate_chapter_response, get_compiled_graph
from app.modules.ChapterStudio_V1.pipeline.graph import build_chapter_studio_graph


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
    # 로컬 .env의 LECTURE_TEXT_MODEL이 ACTIVE_TEXT_MODEL보다 우선해 가짜 커넥터를 덮어쓰지 못하게 한다.
    monkeypatch.delenv("LECTURE_TEXT_MODEL", raising=False)
    monkeypatch.setenv("ACTIVE_TEXT_MODEL", "unit_fake")
    # 이 테스트는 그래프 배선만 검증한다. self-repair·content-verify는 각 전용 테스트
    # (test_generate_repair / test_content_verify)에서 다루므로 여기서는 끈다.
    monkeypatch.setenv("CHAPTERSTUDIO_LESSON_SELF_REPAIR", "false")
    monkeypatch.setenv("CHAPTERSTUDIO_CONTENT_VERIFY", "false")
    monkeypatch.setenv("VOICE_COHESION_ENABLED", "false")
    # Kanana 교정·음성 자동생성은 실제 Modal 호출이라 그래프 배선 테스트에서는 끈다.
    # (각 전용 테스트 test_kanana_polish_pipeline / test_synthesize_audio_node에서 mock으로 검증)
    monkeypatch.setenv("KANANA_POLISH_ENABLED", "0")
    monkeypatch.setenv("TTS_AUTOGEN_ENABLED", "0")
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


def test_graph_routes_synthesize_audio_before_postprocess() -> None:
    graph = build_chapter_studio_graph().get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert "synthesize_audio" in graph.nodes
    assert ("content_verify", "synthesize_audio") in edges
    assert ("synthesize_audio", "postprocess_slides") in edges


def _payload(slide_count: int) -> dict[str, object]:
    return {
        "slides": [_slide(idx) for idx in range(slide_count)],
        "quizzes": [_quiz(idx) for idx in range(slide_count)],
        "note_blocks": [_note(idx) for idx in range(3)],
        "assignment": {
            "title": "실습 과제",
            "assignment_format": "서술형",
            "expected_minutes": 20,
            "steps": ["개념을 설명합니다."],
            "rubric": ["근거를 확인합니다."],
        },
        "voice_scripts": [
            {"slide_idx": idx, "script_text": _voice_text()} for idx in range(slide_count)
        ],
    }


def _note(idx: int) -> dict[str, object]:
    return {
        "heading": f"핵심 {idx}",
        "bullets": ["핵심 개념을 한 문장으로 다시 정리해 복습합니다.", "실수하기 쉬운 경계 조건을 직접 점검합니다."],
    }


def _voice_text() -> str:
    # self-check 하한(700자/7문장)을 넘기는 충분히 풍부한 과외 말투 대본이다.
    sentence = "자, 이번 화면에서는 핵심 개념을 왜 이렇게 봐야 하는지 직관부터 차근차근 풀어서 설명해 보겠습니다."
    return " ".join(sentence for _ in range(9))


def _slide(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "title": f"슬라이드 {idx}",
        "focus": "핵심 흐름",
        "checkpoint": "자가점검",
        "category": "text",
        "html": (
            "<section><h2>핵심 개념을 한 화면에서 정리합니다.</h2>"
            "<p>먼저 이 개념이 왜 중요한지 배경을 설명합니다.</p>"
            "<p>다음으로 실제 동작 방식을 예시와 함께 살펴봅니다.</p>"
            "<p>마지막으로 자주 틀리는 지점을 짚고 넘어갑니다.</p></section>"
        ),
        "css": "",
    }


def _quiz(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "question": "질문입니다.",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "이해",
        "explanation": "정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다.",
    }
