"""컴포넌트 병렬 생성(generate_lesson_parallel) 오프라인 검증.

Modal 없이 fake 커넥터로 다음을 확인한다:
    - slides/quizzes/note/assignment/voice가 asyncio.gather로 동시(병렬) 호출되는지(동시성 관측).
    - 조립 계약 충족: slide_idx 0..n-1 완전집합·개수 일치.
    - assignment.rubric이 dict로 와도 list로 정규화돼 통과하는지.
    - 한 컴포넌트가 첫 호출에 실패해도 1회 재시도로 복구하는지.
    - 재시도 후에도 실패하면 ConversionError로 드러나는지(삼키지 않음).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.parallel_generate import generate_lesson_parallel
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState

_SLIDE_COUNT = 10

_VOICE_TEXT = (
    "자, 이번 화면에서는 핵심 개념을 직관부터 차근차근 설명하고, 실수하기 쉬운 경계 조건을 "
    "작은 예시로 직접 짚어 본 뒤 미니 연습으로 자연스럽게 마무리하겠습니다. 한 번 더 정리하면, "
    "왜 이렇게 동작하는지 이유까지 함께 이해하는 것이 중요합니다. 천천히 따라와 주세요."
)
_QUIZ_EXPLANATION = (
    "정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다. "
    "경계 조건을 놓치는 약점과 직접 연결되므로 종료 조건을 끝까지 따지는 습관이 필요합니다."
)


def _state() -> ChapterStudioState:
    return {
        "slide_count": _SLIDE_COUNT,
        "template_key": "concept_flow",
        "enriched_brief": "정렬 알고리즘 강의 brief",
        "slide_outline": [
            {"slide_idx": idx, "category": "text", "role": f"역할 {idx}", "must_have": []}
            for idx in range(_SLIDE_COUNT)
        ],
    }


@pytest.mark.anyio
async def test_components_generated_in_parallel_and_satisfy_contract() -> None:
    connector = _ComponentConnector(rubric_as_dict=True)

    payload = await generate_lesson_parallel(connector, _state(), _SLIDE_COUNT)

    # 개수·인덱스 완전집합 계약.
    assert {s.slide_idx for s in payload.slides} == set(range(_SLIDE_COUNT))
    assert {q.slide_idx for q in payload.quizzes} == set(range(_SLIDE_COUNT))
    assert {v.slide_idx for v in payload.voice_scripts} == set(range(_SLIDE_COUNT))
    assert len(payload.note_blocks) == 4
    # dict rubric이 list로 정규화돼 통과해야 한다.
    assert isinstance(payload.assignment.rubric, list)
    assert isinstance(payload.assignment.steps, list)
    # gather로 동시 실행됐다면 최대 동시 호출이 1보다 커야 한다(직렬이면 1).
    assert connector.max_active > 1


@pytest.mark.anyio
async def test_component_failure_recovers_via_single_retry() -> None:
    # slides 컴포넌트가 첫 호출에만 깨진 응답을 주고 재시도엔 정상 응답을 준다.
    connector = _ComponentConnector(fail_once_schema="slides")

    payload = await generate_lesson_parallel(connector, _state(), _SLIDE_COUNT)

    assert {s.slide_idx for s in payload.slides} == set(range(_SLIDE_COUNT))
    # 재시도가 실제로 한 번 더 일어났는지(slides 호출이 2회).
    assert connector.calls_by_schema["slides"] == 2


@pytest.mark.anyio
async def test_component_persistent_failure_raises_conversion_error() -> None:
    # quizzes가 재시도 후에도 계속 깨지면 ConversionError로 드러나야 한다(삼키지 않음).
    connector = _ComponentConnector(always_fail_schema="quizzes")

    with pytest.raises(ConversionError):
        await generate_lesson_parallel(connector, _state(), _SLIDE_COUNT)


# ── fake 커넥터 ──────────────────────────────────────────────────────


class _ComponentConnector:
    """schema_kind별로 해당 컴포넌트 응답을 주는 batch 지원(=Qwen 인지) fake 커넥터."""

    name = "component_fake"

    def __init__(
        self,
        rubric_as_dict: bool = False,
        fail_once_schema: str | None = None,
        always_fail_schema: str | None = None,
    ) -> None:
        self._rubric_as_dict = rubric_as_dict
        self._fail_once_schema = fail_once_schema
        self._always_fail_schema = always_fail_schema
        self.active = 0
        self.max_active = 0
        self.calls_by_schema: dict[str, int] = {}

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        schema = str(req.extra.get("schema", ""))
        self.calls_by_schema[schema] = self.calls_by_schema.get(schema, 0) + 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            # 모든 컴포넌트가 동시에 머무는 구간을 만들어 gather 동시성을 관측 가능하게 한다.
            await asyncio.sleep(0.02)
            return self._respond(req, schema)
        finally:
            self.active -= 1

    def _respond(self, req: ChapterAIRequest, schema: str) -> ChapterAIResponse:
        if schema == self._always_fail_schema:
            return _resp("깨진 응답입니다(JSON 아님).")
        if schema == self._fail_once_schema and self.calls_by_schema[schema] == 1:
            return _resp("깨진 응답입니다(JSON 아님).")
        return _resp(self._body(req, schema))

    def _body(self, req: ChapterAIRequest, schema: str) -> str:
        if schema == "slides":
            return json.dumps({"slides": [_slide(i) for i in range(_SLIDE_COUNT)]}, ensure_ascii=False)
        if schema == "quizzes":
            return json.dumps({"quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)]}, ensure_ascii=False)
        if schema == "note":
            return json.dumps({"note_blocks": [_note(i) for i in range(4)]}, ensure_ascii=False)
        if schema == "assignment":
            return json.dumps({"assignment": self._assignment()}, ensure_ascii=False)
        if schema == "voice_script":
            # 커넥터는 요청받은 slide_idx를 그대로 echo한다(완전집합 보장).
            slide_idx = int(req.extra.get("slide_idx", 0))
            return json.dumps({"slide_idx": slide_idx, "script_text": _VOICE_TEXT}, ensure_ascii=False)
        raise AssertionError(f"예상치 못한 schema: {schema}")

    def _assignment(self) -> dict[str, object]:
        rubric: object = (
            {"correctness": "정확성", "clarity": "명료성"}
            if self._rubric_as_dict
            else ["근거가 명확한가", "예외 처리가 정확한가"]
        )
        return {
            "title": "실습 과제",
            "assignment_format": "문제풀이+근거 표시",
            "expected_minutes": 30,
            "steps": ["핵심 개념을 직접 적용해 봅니다.", "결과를 근거와 함께 정리합니다."],
            "rubric": rubric,
        }

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return feature in {"batch", "long_context", "shutdown"}


def _resp(text: str) -> ChapterAIResponse:
    return ChapterAIResponse(text=text, model="fake", input_tokens=1, output_tokens=1, finish_reason="stop")


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
