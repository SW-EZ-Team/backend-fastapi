"""병렬 검증 다라운드 + voice 길이 게이트 통합 검증.

오프라인 fake 커넥터로 다음을 확인한다:
    ① 짧은 voice(600자) → 길이 게이트가 교정 대상에 포함 → 커넥터가 확장 응답 → 900+ 달성.
    ② 1라운드 후 잔존 오류 → 2라운드 교정 호출 → 2라운드 후 중단(verify_max_rounds=2 기준).
    ③ voice 충분 + 오류 0건 → no-op(교정 호출 없음).
    ④ CHAPTERSTUDIO_VOICE_LENGTH_GATE=false → 짧은 voice여도 게이트 미동작(no-op).
"""
from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.pipeline.content_verify_parallel import verify_and_correct_parallel
from app.modules.ChapterStudio_V1.pipeline.payload import parse_payload

_SLIDE_COUNT = 10  # GeneratedLessonPayload.slides 최소값(min_length=10)을 만족해야 한다.
_LONG_VOICE = "가" * 950   # 950자 — 게이트 통과
_SHORT_VOICE = "가" * 600  # 600자 — 게이트 미달


@pytest.mark.anyio
async def test_voice_length_gate_triggers_extension_and_reaches_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 환경 설정: 게이트 ON, 2라운드.
    monkeypatch.setenv("CHAPTERSTUDIO_VOICE_LENGTH_GATE", "true")
    monkeypatch.setenv("CHAPTERSTUDIO_VOICE_MIN_CHARS", "900")
    monkeypatch.setenv("CHAPTERSTUDIO_VERIFY_MAX_ROUNDS", "2")

    connector = _VoiceExtendConnector(extend_to=950)
    payload = _short_voice_payload()

    result = await verify_and_correct_parallel(connector, payload, _SLIDE_COUNT)

    # 교정 후 모든 voice가 900자 이상이어야 한다.
    for script in result.voice_scripts:
        assert len(script.script_text.strip()) >= 900, (
            f"slide {script.slide_idx}: {len(script.script_text)}자 (미달)"
        )
    # content_correct 호출이 실제로 발생했다(게이트가 교정을 유발했다).
    assert connector.correct_calls >= 1


@pytest.mark.anyio
async def test_two_rounds_on_persisting_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAPTERSTUDIO_VOICE_LENGTH_GATE", "false")  # 게이트 끔 — LLM 오류만 테스트
    monkeypatch.setenv("CHAPTERSTUDIO_VERIFY_MAX_ROUNDS", "2")

    connector = _TwoRoundConnector()
    payload = _long_voice_payload()

    await verify_and_correct_parallel(connector, payload, _SLIDE_COUNT)

    # 3그룹 동시 검증이므로 verify 1회 = _verify_group 3호출.
    # 라운드1(3) + 라운드2(3) + 최종검증(3) = 9, correct 2회(라운드별 1회씩).
    assert connector.verify_calls == 9
    assert connector.correct_calls == 2


@pytest.mark.anyio
async def test_no_op_when_voice_long_and_no_llm_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAPTERSTUDIO_VOICE_LENGTH_GATE", "true")
    monkeypatch.setenv("CHAPTERSTUDIO_VOICE_MIN_CHARS", "900")

    connector = _CleanConnector()
    payload = _long_voice_payload()

    result = await verify_and_correct_parallel(connector, payload, _SLIDE_COUNT)

    # 오류 0건 + 게이트 통과 → 교정 없이 원본 그대로.
    assert result is payload
    assert connector.correct_calls == 0


@pytest.mark.anyio
async def test_gate_disabled_skips_short_voice_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAPTERSTUDIO_VOICE_LENGTH_GATE", "false")

    connector = _CleanConnector()
    payload = _short_voice_payload()

    result = await verify_and_correct_parallel(connector, payload, _SLIDE_COUNT)

    # 게이트 꺼져 있으면 짧은 voice도 교정 대상에 포함되지 않는다.
    assert result is payload
    assert connector.correct_calls == 0


# ── fake 커넥터 ──────────────────────────────────────────────────────


class _VoiceExtendConnector:
    """verify에선 오류 없음, correct에서 voice를 확장해 돌려주는 커넥터."""

    name = "voice_extend_fake"

    def __init__(self, extend_to: int) -> None:
        self._extend_to = extend_to
        self.correct_calls = 0

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        if req.extra.get("content_verify"):
            return _resp(json.dumps({"errors": []}, ensure_ascii=False))
        if req.extra.get("content_correct"):
            self.correct_calls += 1
            # 모든 slide voice를 extend_to자로 확장한 교정 응답을 만든다.
            scripts = [
                {"slide_idx": i, "script_text": "나" * self._extend_to}
                for i in range(_SLIDE_COUNT)
            ]
            return _resp(json.dumps({"voice_scripts": scripts}, ensure_ascii=False))
        raise AssertionError(f"예상치 못한 호출: {req.extra}")

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


class _TwoRoundConnector:
    """correct를 1회 받을 때까지 오류를 보고하다가 2번째 correct부터는 클린한 커넥터.

    라운드1 검증 → correct(1회) → 라운드2 검증 → 여전히 오류 → correct(2회) → 최종 검증 → 클린
    이 흐름을 재현해 max_rounds=2에서 correct가 정확히 2회 호출됨을 검증한다.
    """

    name = "two_round_fake"

    def __init__(self) -> None:
        self.verify_calls = 0
        self.correct_calls = 0

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        if req.extra.get("content_verify"):
            self.verify_calls += 1
            # correct가 2회 완료된 이후부터 클린 — 그 전까지는 오류 1건 유지.
            if self.correct_calls < 2:
                return _resp(json.dumps({"errors": [_slide_error(0)]}, ensure_ascii=False))
            return _resp(json.dumps({"errors": []}, ensure_ascii=False))
        if req.extra.get("content_correct"):
            self.correct_calls += 1
            return _resp(json.dumps({"slides": [], "quiz_explanations": [], "voice_scripts": []}, ensure_ascii=False))
        raise AssertionError(f"예상치 못한 호출: {req.extra}")

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


class _CleanConnector:
    """항상 오류 0건을 반환하는 커넥터."""

    name = "clean_fake"

    def __init__(self) -> None:
        self.correct_calls = 0

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        if req.extra.get("content_correct"):
            self.correct_calls += 1
        return _resp(json.dumps({"errors": []}, ensure_ascii=False))

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


def _slide_error(idx: int) -> dict:
    return {
        "location": f"slide {idx}",
        "field": "slide",
        "slide_idx": idx,
        "what_is_wrong": "잘못된 정의가 포함돼 있다.",
        "correction": "올바른 정의로 교체한다.",
    }


def _resp(text: str) -> ChapterAIResponse:
    return ChapterAIResponse(text=text, model="fake", input_tokens=1, output_tokens=1, finish_reason="stop")


# ── 합성 payload ────────────────────────────────────────────────────


def _long_voice_payload():
    return parse_payload(json.dumps(_raw_dict(_LONG_VOICE), ensure_ascii=False), _SLIDE_COUNT)


def _short_voice_payload():
    return parse_payload(json.dumps(_raw_dict(_SHORT_VOICE), ensure_ascii=False), _SLIDE_COUNT)


def _raw_dict(voice_text: str) -> dict:
    return {
        "slides": [_slide(i) for i in range(_SLIDE_COUNT)],
        "quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)],
        "note_blocks": [_note(i) for i in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [{"slide_idx": i, "script_text": voice_text} for i in range(_SLIDE_COUNT)],
    }


def _slide(idx: int) -> dict:
    return {
        "slide_idx": idx, "title": f"슬라이드 {idx}", "focus": "핵심", "checkpoint": "점검",
        "category": "text",
        "html": "<section><p>핵심 개념을 차근차근 설명합니다. 기초부터 쌓아가며 이해해 봅시다.</p></section>",
        "css": "",
    }


def _quiz(idx: int) -> dict:
    return {
        "slide_idx": idx, "question": "질문입니다.", "choices": ["A", "B", "C", "D"],
        "answer_idx": 0, "difficulty": "이해",
        "explanation": "정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다.",
    }


def _note(idx: int) -> dict:
    return {
        "heading": f"핵심 {idx}",
        "bullets": [
            "핵심 개념을 한 문장으로 다시 정리하면서 배경까지 복습합니다.",
            "실수하기 쉬운 경계 조건을 직접 예시로 점검합니다.",
            "오해하기 쉬운 부분을 반례와 함께 짚습니다.",
        ],
    }


def _assignment() -> dict:
    return {
        "title": "실습 과제", "assignment_format": "문제풀이", "expected_minutes": 25,
        "steps": ["개념을 적용합니다.", "결과를 정리합니다."],
        "rubric": ["근거가 명확한가", "예외 처리가 정확한가"],
    }
