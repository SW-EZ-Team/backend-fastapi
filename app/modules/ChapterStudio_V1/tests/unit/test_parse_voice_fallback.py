"""parse_voice raw 텍스트 폴백 검증.

Qwen이 guided_json을 무시하고 대본 자체를 raw 텍스트로 반환하는 비결정적 케이스
(추출길이=원본길이, JSON 경계 못 찾음)에 대한 폴백 동작을 확인한다.

검증 항목:
    ① 정상 JSON 응답 → 기존 경로(slide_idx·script_text 모두 JSON에서)
    ② raw 한국어 대본(JSON 아님) → 폴백으로 script_text 확보 + 올바른 slide_idx
    ③ raw 텍스트 앞뒤 따옴표 제거
    ④ <think> + 마크다운 펜스 제거
    ⑤ 폴백 텍스트가 900자 미만이면 voice 길이 게이트 미달 항목으로 잡힘
    ⑥ _gather_voices가 partial로 slide_idx를 각 파서에 바인딩하는지
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.pipeline.parallel_prompts import _clean_raw_voice_text, parse_voice
from app.modules.ChapterStudio_V1.pipeline.voice_length_gate import length_gate_errors

# 테스트용 정상 script_text — 900자 이상, 길이 게이트 통과용.
_LONG_SCRIPT = "이번 화면에서는 핵심 개념을 직관부터 차근차근 설명합니다. " * 30
# 길이 게이트 미달용 — 400자.
_SHORT_SCRIPT = "짧은 대본." * 20


# ── ① 정상 JSON 경로 ──────────────────────────────────────────────────

def test_normal_json_parses_correctly() -> None:
    """정상 JSON 응답 → slide_idx·script_text 모두 JSON에서 가져온다."""
    body = json.dumps({"slide_idx": 3, "script_text": _LONG_SCRIPT}, ensure_ascii=False)
    result = parse_voice(body, slide_idx=3)
    assert result.slide_idx == 3
    assert result.script_text == _LONG_SCRIPT


def test_normal_json_ignores_fallback_idx() -> None:
    """정상 JSON이면 JSON의 slide_idx를 사용한다(fallback_idx는 쓰이지 않는다)."""
    body = json.dumps({"slide_idx": 7, "script_text": _LONG_SCRIPT}, ensure_ascii=False)
    # 폴백 slide_idx와 JSON slide_idx가 다른 경우 — JSON 값이 우선.
    result = parse_voice(body, slide_idx=99)
    assert result.slide_idx == 7


# ── ② raw 텍스트 폴백 ────────────────────────────────────────────────

def test_raw_korean_text_falls_back_with_correct_slide_idx() -> None:
    """raw 한국어 대본(JSON 아님) → 폴백으로 script_text 확보 + 호출부 slide_idx 사용."""
    raw_text = _LONG_SCRIPT  # JSON 구조 없는 순수 텍스트
    result = parse_voice(raw_text, slide_idx=5)
    assert result.slide_idx == 5
    assert len(result.script_text) > 0
    assert "핵심 개념" in result.script_text


def test_raw_text_fallback_uses_provided_slide_idx_not_zero() -> None:
    """폴백 시 slide_idx는 호출부가 제공한 값 — 0이 아닌 임의 인덱스를 보존한다."""
    result = parse_voice("완전한 자연어 응답입니다 " * 50, slide_idx=9)
    assert result.slide_idx == 9


# ── ③ 앞뒤 따옴표 제거 ────────────────────────────────────────────────

def test_clean_raw_voice_strips_surrounding_quotes() -> None:
    """앞뒤 큰따옴표로 감싸인 경우 벗겨낸다(JSON 문자열 리터럴 잔재)."""
    quoted = f'"{_LONG_SCRIPT}"'
    cleaned = _clean_raw_voice_text(quoted)
    assert not cleaned.startswith('"')
    assert not cleaned.endswith('"')
    assert "핵심 개념" in cleaned


def test_clean_raw_voice_leaves_unquoted_text_intact() -> None:
    """따옴표 없는 텍스트는 그대로 둔다(trim만)."""
    text = "  이번 화면에서는 핵심 개념을 설명합니다.  "
    assert _clean_raw_voice_text(text) == "이번 화면에서는 핵심 개념을 설명합니다."


def test_clean_raw_voice_removes_think_and_fence() -> None:
    """<think> 블록 + 코드펜스 제거 후 본문만 남긴다."""
    with_think = f"<think>추론 중</think>\n{_LONG_SCRIPT}"
    cleaned = _clean_raw_voice_text(with_think)
    assert "<think>" not in cleaned
    assert "핵심 개념" in cleaned


# ── ④ 폴백 텍스트 + 길이 게이트 ──────────────────────────────────────

def test_short_fallback_text_caught_by_length_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """폴백으로 얻은 script_text가 900자 미만이면 길이 게이트 미달 항목으로 잡힌다."""
    import json as _json
    from app.modules.ChapterStudio_V1.pipeline.payload import parse_payload

    # 짧은 raw 텍스트 폴백으로 voice를 얻는다(400자, 게이트 미달).
    short_voice_result = parse_voice(_SHORT_SCRIPT, slide_idx=0)
    assert len(short_voice_result.script_text) < 900

    # 이 voice_script를 payload에 넣고 길이 게이트를 돌린다.
    slide_count = 10
    payload = parse_payload(
        _json.dumps(_payload_dict(short_voice_result.script_text, slide_count), ensure_ascii=False),
        slide_count,
    )
    gate_errors = length_gate_errors(payload, min_chars=900)
    # slide 0이 미달이므로 게이트 오류에 포함돼야 한다.
    assert any(int(e["slide_idx"]) == 0 for e in gate_errors)
    assert all(e["field"] == "voice" for e in gate_errors)


def test_long_fallback_text_passes_length_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """폴백으로 얻은 script_text가 900자 이상이면 길이 게이트를 통과한다."""
    import json as _json
    from app.modules.ChapterStudio_V1.pipeline.payload import parse_payload

    long_voice_result = parse_voice(_LONG_SCRIPT, slide_idx=0)
    assert len(long_voice_result.script_text) >= 900

    slide_count = 10
    payload = parse_payload(
        _json.dumps(_payload_dict(long_voice_result.script_text, slide_count), ensure_ascii=False),
        slide_count,
    )
    gate_errors = length_gate_errors(payload, min_chars=900)
    assert gate_errors == []


# ── ⑥ _gather_voices partial 바인딩 ──────────────────────────────────

@pytest.mark.anyio
async def test_gather_voices_binds_slide_idx_per_target() -> None:
    """_gather_voices가 각 voice 타깃별로 올바른 slide_idx를 바인딩하는지 확인한다.

    raw 텍스트 응답으로 폴백이 발동할 때 각 슬라이드의 인덱스가 뒤섞이지 않아야 한다.
    """
    from functools import partial

    from app.modules.ChapterStudio_V1.pipeline.parallel_generate import _gather_voices
    from app.modules.ChapterStudio_V1.pipeline.parallel_inputs import VoiceTarget

    # 모든 요청에 raw 텍스트를 돌려주는 커넥터 — parse_voice 폴백을 유발한다.
    connector = _RawTextConnector(raw_text=_LONG_SCRIPT)
    brief = "테스트 강의"
    targets = [VoiceTarget(slide_idx=i, title=f"제목{i}", focus=f"초점{i}", summary="요약") for i in range(5)]

    voices = await _gather_voices(connector, brief, 5, targets)

    # 각 voice의 slide_idx가 요청 순서와 일치해야 한다(인덱스 뒤섞임 없음).
    for expected_idx, voice in enumerate(voices):
        assert voice.slide_idx == expected_idx, (
            f"slide {expected_idx}: partial 바인딩 실패, 실제 slide_idx={voice.slide_idx}"
        )


# ── fake 보조 ─────────────────────────────────────────────────────────


class _RawTextConnector:
    """항상 raw 텍스트를 반환해 parse_voice 폴백을 유발하는 커넥터."""

    name = "raw_text_fake"

    def __init__(self, raw_text: str) -> None:
        self._raw = raw_text

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        return ChapterAIResponse(
            text=self._raw, model="fake", input_tokens=1, output_tokens=1, finish_reason="stop"
        )

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return feature in {"batch", "long_context"}


def _payload_dict(voice_text: str, slide_count: int) -> dict:
    return {
        "slides": [_slide(i) for i in range(slide_count)],
        "quizzes": [_quiz(i) for i in range(slide_count)],
        "note_blocks": [_note(i) for i in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [
            {"slide_idx": i, "script_text": voice_text if i == 0 else _LONG_SCRIPT}
            for i in range(slide_count)
        ],
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
        "slide_idx": idx, "question": "질문.", "choices": ["A", "B", "C", "D"],
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
