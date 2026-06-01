"""generate_node의 견고 파싱 경로(엄격 실패→관대+보충→최종 검증) end-to-end 검증.

실제 Modal 출력 특성을 fake 커넥터로 재현한다:
    - codex 흐름: 첫 응답이 10/10/10 정확 → 엄격 파싱 바로 통과, 보충 호출 0(no-op).
    - Qwen 흐름: 첫 응답이 quizzes/voice 부족 + rubric dict → 관대 파싱 후 보충으로 계약 충족.
Modal은 호출하지 않으며, 보충 응답도 fake 커넥터가 schema_kind별로 시뮬레이션한다.
"""
from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.pipeline.nodes.generate_node import _parse_robust

_QUIZ_EXPLANATION = (
    "정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다. "
    "경계 조건을 놓치는 약점과 직접 연결되므로 종료 조건을 끝까지 따지는 습관이 필요합니다."
)
_VOICE_TEXT = (
    "이번 슬라이드에서는 핵심 개념을 직관부터 차근차근 설명하고, 실수하기 쉬운 경계 "
    "조건을 작은 예시로 직접 짚어 본 뒤 미니 연습으로 자연스럽게 마무리하겠습니다."
)


@pytest.mark.anyio
async def test_codex_complete_output_takes_strict_fast_path() -> None:
    # codex처럼 첫 응답이 완전하면 보충 커넥터가 호출되지 않는다(no-op, 비용 불변).
    connector = _StrictOnlyConnector()
    request = _request()

    payload = await _parse_robust(connector, request, _complete_text(10), 10)

    assert len(payload.quizzes) == 10
    assert len(payload.voice_scripts) == 10
    assert connector.calls == 0  # 첫 텍스트를 인자로 받았으므로 generate 추가 호출 없음


@pytest.mark.anyio
async def test_qwen_deficient_output_recovers_via_backfill() -> None:
    # Qwen 실측: quizzes 5개 + voice 5개 + rubric dict → 관대 파싱 후 보충으로 계약 충족.
    connector = _BackfillConnector()
    request = _request()

    payload = await _parse_robust(connector, request, _deficient_text(10), 10)

    assert {q.slide_idx for q in payload.quizzes} == set(range(10))
    assert {v.slide_idx for v in payload.voice_scripts} == set(range(10))
    assert {s.slide_idx for s in payload.slides} == set(range(10))
    # rubric dict가 list로 정규화돼 통과해야 한다.
    assert isinstance(payload.assignment.rubric, list)


# ── fake 커넥터 ──────────────────────────────────────────────────────


class _StrictOnlyConnector:
    """generate를 호출하면 실패시키는 커넥터 — 첫 텍스트만으로 통과하는지 검증용."""

    name = "strict_only"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        self.calls += 1
        raise AssertionError("완전한 첫 응답이면 generate 추가 호출이 없어야 한다.")

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        raise AssertionError("호출되면 안 된다.")

    def supports(self, feature: str) -> bool:
        return True


class _BackfillConnector:
    """누락 quiz/voice를 schema_kind별로 채워 주는 보충 커넥터(테스트용)."""

    name = "backfill_fake"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        schema = str(req.extra.get("schema", ""))
        if schema == "supporting_materials":
            missing = [idx for idx in range(15) if f"slide {idx}:" in req.user]
            body = {"quizzes": [_quiz(idx) for idx in missing], "assignment": _assignment()}
            return _resp(json.dumps(body, ensure_ascii=False))
        if schema == "voice_script":
            slide_idx = int(req.extra.get("slide_idx", 0))
            return _resp(json.dumps({"slide_idx": slide_idx, "script_text": _VOICE_TEXT}, ensure_ascii=False))
        raise AssertionError(f"예상치 못한 schema: {schema}")

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


def _resp(text: str) -> ChapterAIResponse:
    return ChapterAIResponse(text=text, model="fake", input_tokens=1, output_tokens=1, finish_reason="stop")


def _request() -> ChapterAIRequest:
    return ChapterAIRequest(system="sys", user="원본 사용자 프롬프트", max_tokens=4096, temperature=0.2)


# ── 합성 텍스트 ──────────────────────────────────────────────────────


def _complete_text(slide_count: int) -> str:
    return json.dumps(_payload_dict(slide_count), ensure_ascii=False)


def _deficient_text(slide_count: int) -> str:
    data = _payload_dict(slide_count)
    data["quizzes"] = data["quizzes"][:5]
    data["voice_scripts"] = data["voice_scripts"][:5]
    data["assignment"]["rubric"] = {"correctness": "정확성", "clarity": "명료성"}
    return json.dumps(data, ensure_ascii=False)


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
