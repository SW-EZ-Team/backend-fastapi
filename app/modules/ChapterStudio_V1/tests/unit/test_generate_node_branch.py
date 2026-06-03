"""generate_lesson_node의 모델 인지 분기 검증.

connector.supports("batch")에 따라:
    - True(=Qwen Modal, CodexCLI): 컴포넌트 병렬 경로(generate_lesson_parallel)를 탄다.
    - False(=claude): 기존 단일 거대 콜 경로를 그대로 탄다(동작·비용 불변).

P0 픽스: CodexCLIConnector는 "batch"를 지원하므로 단일 거대 콜(180초 타임아웃)이 아닌
         컴포넌트별 병렬 경로를 탄다.
"""
from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors import registry
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.pipeline.nodes import generate_node
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState

_SLIDE_COUNT = 10
_VOICE_TEXT = (
    "자, 이번 화면에서는 핵심 개념을 직관부터 차근차근 설명하고, 실수하기 쉬운 경계 조건을 작은 "
    "예시로 직접 짚어 본 뒤 미니 연습으로 자연스럽게 마무리하겠습니다. 왜 이렇게 동작하는지 이유까지 "
    "함께 이해하는 것이 핵심입니다. 천천히 한 번 더 정리해 봅시다. 끝까지 따라와 주세요."
)
_QUIZ_EXPLANATION = (
    "정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다. "
    "경계 조건을 놓치는 약점과 직접 연결되므로 종료 조건을 끝까지 따지는 습관이 필요합니다."
)


@pytest.fixture(autouse=True)
def _no_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    # 이 테스트는 분기만 검증한다. self-repair는 끄고 결과 경로만 본다.
    monkeypatch.setenv("CHAPTERSTUDIO_LESSON_SELF_REPAIR", "false")


@pytest.mark.anyio
async def test_batch_connector_takes_parallel_component_path(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _ComponentConnector()
    monkeypatch.setattr(generate_node, "get_text_connector", lambda: connector)

    result = await generate_node.generate_lesson_node(_state())

    # 컴포넌트 스키마별 호출이 실제로 일어났다(=병렬 경로).
    assert "slides" in connector.seen_schemas
    assert "quizzes" in connector.seen_schemas
    assert "assignment" in connector.seen_schemas
    assert "voice_script" in connector.seen_schemas
    # 단일 거대 콜(lesson 스키마)은 타지 않았다.
    assert "lesson" not in connector.seen_schemas
    assert result["generation_model"].endswith("_parallel")
    payload = result["lesson_payload"]
    assert {s["slide_idx"] for s in payload["slides"]} == set(range(_SLIDE_COUNT))


@pytest.mark.anyio
async def test_non_batch_connector_takes_single_call_path(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _SingleCallConnector()
    monkeypatch.setattr(generate_node, "get_text_connector", lambda: connector)

    result = await generate_node.generate_lesson_node(_state())

    # batch 미지원 커넥터만 lesson 단일콜 경로를 탄다.
    assert connector.calls == 1
    assert result["generation_model"] == connector.name
    payload = result["lesson_payload"]
    assert {s["slide_idx"] for s in payload["slides"]} == set(range(_SLIDE_COUNT))


def test_codex_cli_connector_supports_batch() -> None:
    """P0 픽스 확인: CodexCLIConnector가 'batch'를 지원해 병렬 경로를 탄다.

    codex_cli가 'batch' 미지원이면 단일 거대 콜(12슬라이드+퀴즈+voice_scripts)이 180초를
    초과해 강의 생성 전면 실패한다. 이 테스트가 깨지면 P0 타임아웃이 재발한다.
    """
    from app.modules.ChapterStudio_V1.ai_connectors.codex_cli_connector import CodexCLIConnector

    connector = CodexCLIConnector()
    assert connector.supports("batch"), (
        "CodexCLIConnector must support 'batch' to route to generate_lesson_parallel. "
        "단일 거대 콜 경로는 180초 타임아웃을 초과한다(P0)."
    )


def _state() -> ChapterStudioState:
    # 병렬 경로는 enriched_brief/template_key/slide_outline만 쓰지만, 단일콜 경로(build_generation_request)는
    # topic·duration_days·tone 등 풀 상태를 요구하므로 두 경로 모두 만족하도록 채운다.
    return {
        "slide_count": _SLIDE_COUNT,
        "template_key": "algorithm_trace",
        "topic": "정렬 알고리즘",
        "enriched_brief": "정렬 알고리즘 강의 brief",
        "duration_days": 7,
        "tone": 0,
        "pace": 0,
        "tutor_depth": 0,
        "socratic": 0,
        "slide_outline": [
            {"slide_idx": idx, "category": "text", "role": f"역할 {idx}", "must_have": []}
            for idx in range(_SLIDE_COUNT)
        ],
    }


class _ComponentConnector:
    name = "component_fake"

    def __init__(self) -> None:
        self.seen_schemas: set[str] = set()

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        schema = str(req.extra.get("schema", "lesson"))
        self.seen_schemas.add(schema)
        return _resp(_component_body(req, schema))

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return feature in {"batch", "long_context", "shutdown"}


class _SingleCallConnector:
    name = "codex_fake"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        self.calls += 1
        return _resp(json.dumps(_lesson_dict(), ensure_ascii=False))

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return feature == "json_mode"


def _component_body(req: ChapterAIRequest, schema: str) -> str:
    if schema == "slides":
        return json.dumps({"slides": [_slide(i) for i in range(_SLIDE_COUNT)]}, ensure_ascii=False)
    if schema == "quizzes":
        return json.dumps({"quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)]}, ensure_ascii=False)
    if schema == "note":
        return json.dumps({"note_blocks": [_note(i) for i in range(4)]}, ensure_ascii=False)
    if schema == "assignment":
        return json.dumps({"assignment": _assignment()}, ensure_ascii=False)
    if schema == "voice_script":
        slide_idx = int(req.extra.get("slide_idx", 0))
        return json.dumps({"slide_idx": slide_idx, "script_text": _VOICE_TEXT}, ensure_ascii=False)
    raise AssertionError(f"예상치 못한 schema: {schema}")


def _lesson_dict() -> dict[str, object]:
    return {
        "slides": [_slide(i) for i in range(_SLIDE_COUNT)],
        "quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)],
        "note_blocks": [_note(i) for i in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [{"slide_idx": i, "script_text": _VOICE_TEXT} for i in range(_SLIDE_COUNT)],
    }


def _resp(text: str) -> ChapterAIResponse:
    return ChapterAIResponse(text=text, model="codex_fake", input_tokens=1, output_tokens=1, finish_reason="stop")


def _slide(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "title": f"슬라이드 {idx}",
        "focus": "핵심 흐름",
        "checkpoint": "자가점검",
        "category": "text",
        "html": "<section><p>핵심 개념을 차근차근 설명하는 본문입니다.</p></section>",
        "css": "",
    }


def _quiz(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "question": f"슬라이드 {idx} 질문입니다.",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "이해",
        "explanation": _QUIZ_EXPLANATION,
    }


def _note(idx: int) -> dict[str, object]:
    return {
        "heading": f"핵심 {idx}",
        "bullets": [
            "핵심 개념을 한 문장으로 다시 정리하면서 왜 중요한지 배경까지 복습합니다.",
            "실수하기 쉬운 경계 조건을 작은 예시로 직접 점검하는 습관을 만듭니다.",
            "오해하기 쉬운 부분을 반례와 함께 짚어 정확한 판단 기준을 세웁니다.",
        ],
    }


def _assignment() -> dict[str, object]:
    return {
        "title": "실습 과제",
        "assignment_format": "문제풀이+근거 표시",
        "expected_minutes": 30,
        "steps": ["핵심 개념을 직접 적용해 봅니다.", "결과를 근거와 함께 정리합니다."],
        "rubric": ["근거가 명확한가", "예외 처리가 정확한가"],
    }
