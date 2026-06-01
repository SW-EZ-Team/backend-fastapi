"""병렬 2차 검증·교정(verify_and_correct_parallel) 오프라인 검증.

Modal 없이 fake verifier 커넥터로 다음을 확인한다:
    - 슬라이드/퀴즈/음성 검증이 동시에 호출되는지(gather 동시성 관측).
    - slide 그룹 오류가 검출되면 해당 그룹만 병렬 교정돼 본문이 바뀌는지.
    - 모든 그룹 오류 0건이면 교정 없이 원본을 그대로 돌려주는지(오탐 방지).
    - 검증 응답이 깨지면 원본을 유지하는지(graceful, 예외로 죽지 않음).
    - 인덱스 계약이 교정 후에도 보존되는지.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.pipeline.content_verify_parallel import verify_and_correct_parallel
from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload, parse_payload

_SLIDE_COUNT = 10
_WRONG_STACK = "스택(stack)은 FIFO 구조로, 먼저 넣은 값이 먼저 나오는 자료구조입니다."
_FIXED_STACK = "스택(stack)은 LIFO 구조로, 나중에 넣은 값이 먼저 나오는 자료구조입니다."


@pytest.mark.anyio
async def test_groups_verified_in_parallel_and_slide_error_corrected() -> None:
    payload = _payload()
    assert _WRONG_STACK in _slide_html(payload, 2)
    connector = _ParallelVerifyConnector()

    corrected = await verify_and_correct_parallel(connector, payload, _SLIDE_COUNT)

    # slide 2가 교정되고 다른 슬라이드는 불변, 인덱스 계약 보존.
    assert _FIXED_STACK in _slide_html(corrected, 2)
    assert _WRONG_STACK not in _slide_html(corrected, 2)
    assert _slide_html(corrected, 0) == _slide_html(payload, 0)
    assert {s.slide_idx for s in corrected.slides} == set(range(_SLIDE_COUNT))
    assert {v.slide_idx for v in corrected.voice_scripts} == set(range(_SLIDE_COUNT))
    # 세 그룹 검증이 동시에 실행됐다면 최대 동시 호출이 1보다 크다.
    assert connector.max_active > 1


@pytest.mark.anyio
async def test_clean_payload_returned_unchanged() -> None:
    payload = _payload()
    connector = _CleanConnector()

    result = await verify_and_correct_parallel(connector, payload, _SLIDE_COUNT)

    assert result is payload
    assert connector.correct_called is False


@pytest.mark.anyio
async def test_graceful_on_broken_verify_response() -> None:
    payload = _payload()

    result = await verify_and_correct_parallel(_BrokenConnector(), payload, _SLIDE_COUNT)

    assert result is payload


# ── fake 커넥터 ──────────────────────────────────────────────────────


class _ParallelVerifyConnector:
    """slide 그룹에서 slide 2 오류를 보고하고, slide 교정 요청에 고친 html을 돌려준다."""

    name = "parallel_verify_fake"

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self._verify_calls = 0

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.02)
            return self._respond(req)
        finally:
            self.active -= 1

    def _respond(self, req: ChapterAIRequest) -> ChapterAIResponse:
        if req.extra.get("content_verify"):
            return _resp(self._verify_body(req))
        if req.extra.get("content_correct"):
            return _resp(self._correct_body(req))
        raise AssertionError("검증/교정 외의 호출이 발생했다.")

    def _verify_body(self, req: ChapterAIRequest) -> str:
        # slide 그룹 1차 검증에서만 slide 2 오류를 보고하고, 재검증·다른 그룹은 빈 배열.
        self._verify_calls += 1
        if "field는 slide로 보고한다" in req.user and self._verify_calls <= 3:
            return json.dumps(
                {
                    "errors": [
                        {
                            "location": "slide 2 본문",
                            "field": "slide",
                            "slide_idx": 2,
                            "what_is_wrong": "스택은 LIFO인데 FIFO로 잘못 정의했다.",
                            "correction": "스택은 LIFO 구조다.",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps({"errors": []}, ensure_ascii=False)

    def _correct_body(self, req: ChapterAIRequest) -> str:
        fixed = f"<section><h2>{_FIXED_STACK}</h2><p>한 화면에서 핵심을 정리합니다.</p></section>"
        return json.dumps({"slides": [{"slide_idx": 2, "html": fixed}]}, ensure_ascii=False)

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


class _CleanConnector:
    """모든 그룹에서 오류 0건만 돌려주는 검증 커넥터."""

    name = "clean_fake"

    def __init__(self) -> None:
        self.correct_called = False

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        if req.extra.get("content_correct"):
            self.correct_called = True
        return _resp(json.dumps({"errors": []}, ensure_ascii=False))

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


class _BrokenConnector:
    """검증 응답이 JSON이 아닌 경우(graceful 폴백)."""

    name = "broken_fake"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        return _resp("죄송합니다. 검증을 수행하지 못했습니다.")

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


def _resp(text: str) -> ChapterAIResponse:
    return ChapterAIResponse(text=text, model="fake", input_tokens=1, output_tokens=1, finish_reason="stop")


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
    body = _WRONG_STACK if idx == 2 else "정렬된 배열에서 가운데 값을 보고 절반을 버립니다."
    return {
        "slide_idx": idx,
        "title": f"슬라이드 {idx}",
        "focus": "핵심 흐름",
        "checkpoint": "자가점검",
        "category": "text",
        "html": (
            f"<section><h2>{body}</h2>"
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
    # 900자 이상으로 유지해 voice 길이 게이트를 no-op으로 만든다(테스트의 관심사는 LLM 오류 검출).
    sentence = "자, 이번 화면에서는 핵심 개념을 왜 이렇게 봐야 하는지 직관부터 차근차근 설명해 보겠습니다."
    return " ".join(sentence for _ in range(25))


def _slide_html(payload: GeneratedLessonPayload, slide_idx: int) -> str:
    for slide in payload.slides:
        if slide.slide_idx == slide_idx:
            return slide.html
    raise AssertionError(f"slide {slide_idx}를 찾지 못했다.")
