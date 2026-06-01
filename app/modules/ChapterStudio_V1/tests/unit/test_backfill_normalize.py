"""Qwen Modal 출력 견고화 — dict→list 정규화 + 부족 배열 backfill 오프라인 검증.

실제 Modal 테스트에서 잡힌 두 버그(rubric dict, quizzes 개수 부족)를 합성 픽스처로
재현하고, 정규화·보충 경로가 codex 정상 출력엔 영향 없이(no-op) Qwen 결손만 메우는지
확인한다. fake 커넥터로 부족분 생성을 시뮬레이션한다(Modal 미사용).
"""
from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.backfill import backfill_missing
from app.modules.ChapterStudio_V1.pipeline.normalize import normalize_lesson_dict
from app.modules.ChapterStudio_V1.pipeline.payload import (
    finalize_payload,
    parse_payload,
    parse_payload_lenient,
)

_QUIZ_EXPLANATION = (
    "정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다. "
    "경계 조건을 놓치는 약점과 직접 연결되므로 종료 조건을 끝까지 따지는 습관이 필요합니다."
)
_VOICE_TEXT = (
    "이번 슬라이드에서는 핵심 개념을 왜 이렇게 봐야 하는지 직관부터 차근차근 풀어서 "
    "설명하고, 실수하기 쉬운 경계 조건을 작은 예시로 직접 짚어 보겠습니다. 끝으로 미니 "
    "연습 한 가지를 제안하며 자연스럽게 마무리합니다."
)


# ── 1. dict→list 정규화 ─────────────────────────────────────────────


def test_normalize_converts_rubric_dict_to_list() -> None:
    data = _payload_dict(10)
    data["assignment"]["rubric"] = {"correctness": "정확성", "completeness": "완결성"}

    normalized = normalize_lesson_dict(data)

    rubric = normalized["assignment"]["rubric"]
    assert isinstance(rubric, list)
    assert rubric == ["correctness: 정확성", "completeness: 완결성"]


def test_normalize_converts_steps_dict_to_list() -> None:
    data = _payload_dict(10)
    data["assignment"]["steps"] = {"first": "자료를 읽는다", "second": "근거를 정리한다"}

    normalized = normalize_lesson_dict(data)

    assert normalized["assignment"]["steps"] == ["first: 자료를 읽는다", "second: 근거를 정리한다"]


def test_normalize_is_noop_for_list_input() -> None:
    # codex처럼 이미 list면 객체 동일성까지 보존한다(불필요한 사본 생성 없음).
    data = _payload_dict(10)
    normalized = normalize_lesson_dict(data)
    assert normalized is data


def test_parse_payload_recovers_from_rubric_dict() -> None:
    # 실측 버그: rubric이 dict로 와도 정규화가 흡수해 엄격 파싱을 통과시킨다.
    data = _payload_dict(10)
    data["assignment"]["rubric"] = {"correctness": "정확성", "clarity": "명료성"}

    payload = parse_payload(json.dumps(data, ensure_ascii=False), 10)

    assert payload.assignment.rubric == ["correctness: 정확성", "clarity: 명료성"]


# ── 2. 부족 배열 backfill ────────────────────────────────────────────


@pytest.mark.anyio
async def test_backfill_fills_missing_quizzes_and_voices() -> None:
    # 실측 버그: slide 10개인데 quizzes/voice가 5개만 옴 → backfill이 나머지 5개를 채운다.
    data = _payload_dict(10)
    data["quizzes"] = data["quizzes"][:5]
    data["voice_scripts"] = data["voice_scripts"][:5]
    lenient = parse_payload_lenient(json.dumps(data, ensure_ascii=False))

    filled = await backfill_missing(_BackfillConnector(), lenient, 10)

    assert {q.slide_idx for q in filled.quizzes} == set(range(10))
    assert {v.slide_idx for v in filled.voice_scripts} == set(range(10))
    # 보충 후 최종 엄격 계약을 통과해야 한다.
    payload = finalize_payload(filled, 10)
    assert len(payload.quizzes) == 10
    assert len(payload.voice_scripts) == 10


@pytest.mark.anyio
async def test_backfill_preserves_existing_quizzes() -> None:
    # 이미 있는 quiz(slide 0)는 보충본으로 덮어쓰지 않고 그대로 유지한다.
    data = _payload_dict(10)
    data["quizzes"][0]["question"] = "원본 질문 0"
    data["quizzes"] = data["quizzes"][:5]
    lenient = parse_payload_lenient(json.dumps(data, ensure_ascii=False))

    filled = await backfill_missing(_BackfillConnector(), lenient, 10)

    quiz0 = next(q for q in filled.quizzes if q.slide_idx == 0)
    assert quiz0.question == "원본 질문 0"


@pytest.mark.anyio
async def test_backfill_is_noop_for_complete_codex_output() -> None:
    # codex처럼 10/10/10 정확 출력이면 커넥터를 호출하지 않고 그대로 통과한다.
    data = _payload_dict(10)
    lenient = parse_payload_lenient(json.dumps(data, ensure_ascii=False))

    filled = await backfill_missing(_NoCallConnector(), lenient, 10)

    assert {q.slide_idx for q in filled.quizzes} == set(range(10))
    assert {v.slide_idx for v in filled.voice_scripts} == set(range(10))


@pytest.mark.anyio
async def test_backfill_graceful_on_broken_response() -> None:
    # 보충 응답이 깨지면 채우지 못한 채로 둔다(예외로 죽지 않음). 최종 검증이 결손을 드러낸다.
    data = _payload_dict(10)
    data["quizzes"] = data["quizzes"][:5]
    lenient = parse_payload_lenient(json.dumps(data, ensure_ascii=False))

    filled = await backfill_missing(_BrokenConnector(), lenient, 10)

    assert len(filled.quizzes) == 5
    with pytest.raises(ConversionError):
        finalize_payload(filled, 10)


@pytest.mark.anyio
async def test_backfill_rejects_incomplete_slides() -> None:
    # 슬라이드 본문이 부족하면 보충 불가이므로 명확한 에러로 드러낸다(삼키지 않음).
    data = _payload_dict(10)
    data["slides"] = data["slides"][:9]
    lenient = parse_payload_lenient(json.dumps(data, ensure_ascii=False))

    with pytest.raises(ConversionError):
        await backfill_missing(_BackfillConnector(), lenient, 10)


# ── fake 커넥터 ──────────────────────────────────────────────────────


class _BackfillConnector:
    """누락 slide_idx의 quiz/voice를 채워 주는 정상 보충 커넥터(테스트용)."""

    name = "backfill_fake"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        schema = str(req.extra.get("schema", ""))
        if schema == "supporting_materials":
            return _resp(json.dumps(_quiz_backfill_body(req), ensure_ascii=False))
        if schema == "voice_script":
            slide_idx = int(req.extra.get("slide_idx", 0))
            body = {"slide_idx": slide_idx, "script_text": _VOICE_TEXT}
            return _resp(json.dumps(body, ensure_ascii=False))
        raise AssertionError(f"예상치 못한 schema: {schema}")

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


class _BrokenConnector:
    """보충 응답이 깨진 경우(graceful 폴백 검증용)."""

    name = "broken_backfill"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        return _resp("이건 JSON이 아니라 그냥 사과문입니다.")

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


class _NoCallConnector:
    """부족분이 없으면 호출되면 안 되는 커넥터(no-op 검증용)."""

    name = "nocall_backfill"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        raise AssertionError("부족분이 없으면 보충 호출이 없어야 한다.")

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        raise AssertionError("호출되면 안 된다.")

    def supports(self, feature: str) -> bool:
        return True


def _resp(text: str) -> ChapterAIResponse:
    return ChapterAIResponse(text=text, model="fake", input_tokens=1, output_tokens=1, finish_reason="stop")


def _quiz_backfill_body(req: ChapterAIRequest) -> dict[str, object]:
    """supporting_materials 응답을 흉내 — user 프롬프트에 적힌 누락 인덱스만 채운다."""
    missing = [idx for idx in range(15) if f"slide {idx}:" in req.user]
    return {
        "quizzes": [_quiz(idx) for idx in missing],
        "assignment": _assignment(),
    }


# ── 합성 픽스처 ──────────────────────────────────────────────────────


def _payload_dict(slide_count: int) -> dict[str, object]:
    return {
        "slides": [_slide(idx) for idx in range(slide_count)],
        "quizzes": [_quiz(idx) for idx in range(slide_count)],
        "note_blocks": [_note(idx) for idx in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [{"slide_idx": idx, "script_text": _VOICE_TEXT} for idx in range(slide_count)],
    }


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
