from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.pipeline import voice_cohesion_pass
from app.modules.ChapterStudio_V1.pipeline.nodes.content_verify_node import content_verify_node
from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload, parse_payload

_SLIDE_COUNT = 10


@pytest.mark.anyio
async def test_content_verify_node_applies_voice_cohesion_before_state_emit(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _FakeCohesionConnector()
    monkeypatch.setenv("CHAPTERSTUDIO_CONTENT_VERIFY", "false")
    monkeypatch.setenv("KANANA_POLISH_ENABLED", "0")
    monkeypatch.setenv("VOICE_COHESION_ENABLED", "true")
    monkeypatch.setattr(voice_cohesion_pass.registry, "get_text_connector", lambda: connector)

    result = await content_verify_node(_state(_payload()))

    assert result["voice_scripts"][0]["script_text"].startswith("안녕하세요.")
    assert result["voice_scripts"][1]["script_text"].startswith("흐름을 이어 정수 비교로 넘어가겠습니다.")
    assert "첫 번째 본문은 그대로 유지합니다." in result["voice_scripts"][1]["script_text"]
    assert connector.prompts
    assert "topic=정수와 수직선" in connector.prompts[0]


class _FakeCohesionConnector:
    name = "cohesion_fake"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        self.prompts.append(req.user)
        return ChapterAIResponse(
            text="흐름을 이어 정수 비교로 넘어가겠습니다.",
            model=self.name,
            input_tokens=1,
            output_tokens=1,
            finish_reason="stop",
        )

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return False


def _state(payload: GeneratedLessonPayload) -> dict[str, object]:
    return {
        "lesson_payload": payload.model_dump(),
        "slide_count": _SLIDE_COUNT,
        "topic": "정수와 수직선",
        "use_formal_speech": True,
    }


def _payload() -> GeneratedLessonPayload:
    return parse_payload(json.dumps(_payload_dict(), ensure_ascii=False), _SLIDE_COUNT)


def _payload_dict() -> dict[str, object]:
    return {
        "slides": [_slide(idx) for idx in range(_SLIDE_COUNT)],
        "quizzes": [_quiz(idx) for idx in range(_SLIDE_COUNT)],
        "note_blocks": [_note(idx) for idx in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [{"slide_idx": idx, "script_text": _voice()} for idx in range(_SLIDE_COUNT)],
    }


def _slide(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "title": f"정수 개념 {idx}",
        "focus": "수직선 흐름",
        "checkpoint": "자가점검",
        "category": "text",
        "html": "<section><p>수직선에서 정수의 위치를 확인합니다.</p></section>",
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


def _note(idx: int) -> dict[str, object]:
    return {
        "heading": f"핵심 {idx}",
        "bullets": [
            "핵심 개념을 한 문장으로 다시 정리하면서 배경까지 함께 복습합니다.",
            "실수하기 쉬운 경계 조건을 작은 예시로 직접 손으로 점검합니다.",
            "오해하기 쉬운 부분을 반례와 함께 다시 한 번 짚어 정확한 기준을 세웁니다.",
        ],
    }


def _assignment() -> dict[str, object]:
    return {
        "title": "실습 과제",
        "assignment_format": "문제풀이",
        "expected_minutes": 30,
        "steps": ["핵심 개념을 직접 적용해 봅니다.", "결과를 근거와 함께 정리합니다."],
        "rubric": ["근거가 명확한가", "예외 처리가 정확한가"],
    }


def _voice() -> str:
    return "안녕하세요. 첫 번째 본문은 그대로 유지합니다. 정수와 수직선의 관계를 차분히 설명합니다."
