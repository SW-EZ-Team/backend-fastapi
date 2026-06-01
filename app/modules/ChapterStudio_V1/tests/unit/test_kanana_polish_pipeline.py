from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.pipeline.nodes.content_verify_node import content_verify_node
from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload, parse_payload
from app.modules.ChapterStudio_V1.pipeline import kanana_polish

_SLIDE_COUNT = 10


@pytest.mark.anyio
async def test_kanana_polish_disabled_does_not_call_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAPTERSTUDIO_CONTENT_VERIFY", "false")
    monkeypatch.setenv("KANANA_POLISH_ENABLED", "0")
    monkeypatch.setattr(kanana_polish.registry, "get_polish_connector", _raise_if_called)

    result = await content_verify_node(_state(_payload()))

    assert "절대값" in result["voice_scripts"][0]["script_text"]


@pytest.mark.anyio
async def test_kanana_polish_enabled_updates_voice_and_slide_narration(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _FakePolishConnector()
    monkeypatch.setenv("CHAPTERSTUDIO_CONTENT_VERIFY", "false")
    monkeypatch.setenv("KANANA_POLISH_ENABLED", "1")
    monkeypatch.setenv("KANANA_POLISH_MAX_CONCURRENCY", "3")
    monkeypatch.setattr(kanana_polish.registry, "get_polish_connector", lambda: connector)

    result = await content_verify_node(_state(_payload()))

    assert "절댓값" in result["voice_scripts"][0]["script_text"]
    assert "的" not in result["voice_scripts"][0]["script_text"]
    assert result["slide_drafts"][0]["narration"].startswith("정수의 세계")
    assert "정수의 세계" in result["slide_drafts"][0]["html"]
    assert len(connector.calls) == _SLIDE_COUNT * 2
    assert set(connector.tone_hints) == {"존댓말"}


@pytest.mark.anyio
async def test_kanana_polish_failure_keeps_original_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAPTERSTUDIO_CONTENT_VERIFY", "false")
    monkeypatch.setenv("KANANA_POLISH_ENABLED", "1")
    monkeypatch.setattr(kanana_polish.registry, "get_polish_connector", lambda: _FailingPolishConnector())

    result = await content_verify_node(_state(_payload()))

    assert "정수的世界里" in result["voice_scripts"][0]["script_text"]
    assert "절대값" in result["slide_drafts"][0]["narration"]


class _FakePolishConnector:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.tone_hints: list[str] = []

    async def polish(self, text: str, *, tone_hint: str = "") -> str:
        self.calls.append(text)
        self.tone_hints.append(tone_hint)
        return text.replace("정수的世界里", "정수의 세계").replace("절대값", "절댓값")


class _FailingPolishConnector:
    async def polish(self, text: str, *, tone_hint: str = "") -> str:
        raise RuntimeError("교정 실패")


def _raise_if_called() -> object:
    raise AssertionError("KANANA_POLISH_ENABLED=0에서는 커넥터를 만들면 안 된다.")


def _state(payload: GeneratedLessonPayload) -> dict[str, object]:
    return {
        "lesson_payload": payload.model_dump(),
        "slide_count": _SLIDE_COUNT,
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
    narration = "정수的世界里에서 절대값을 비교할 수 있을까요 스스로 질문합니다."
    return {
        "slide_idx": idx,
        "title": f"슬라이드 {idx}",
        "focus": narration,
        "checkpoint": "자가점검",
        "category": "text",
        "html": f"<section><header><p>{narration}</p></header></section>",
        "css": "",
        "narration": narration,
        "visual": {"type": "example_box", "data": {"problem": "정수", "steps": [narration], "answer": "비교"}},
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
    sentence = "정수的世界里에서 절대값을 비교할 수 있을까요 스스로 질문하며 기준을 정리합니다."
    return " ".join(sentence for _ in range(8))
