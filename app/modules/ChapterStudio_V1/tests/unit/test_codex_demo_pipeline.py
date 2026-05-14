from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.app.codex_demo_pipeline import CodexDemoPayload, _parse_payload, _request, _user_prompt
from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext, ReferenceBookHit
from app.modules.ChapterStudio_V1.common.errors import ConversionError


def test_codex_demo_payload_requires_five_slides() -> None:
    payload = _payload()
    payload["slides"] = payload["slides"][:2]
    with pytest.raises(ConversionError):
        _parse_payload(json.dumps(payload, ensure_ascii=False))


def test_codex_demo_payload_requires_three_note_blocks() -> None:
    payload = _payload()
    payload["note_blocks"] = payload["note_blocks"][:2]
    with pytest.raises(ConversionError):
        _parse_payload(json.dumps(payload, ensure_ascii=False))


def test_codex_demo_payload_accepts_valid_json() -> None:
    payload = _payload()
    parsed = _parse_payload(CodexDemoPayload.model_validate(payload).model_dump_json())
    assert parsed.note_blocks[0].heading == "핵심"
    assert parsed.assignment.assignment_format == "서술형 복습지"
    assert parsed.assignment.expected_minutes == 20
    assert parsed.voice_scripts[0].slide_idx == 0


def test_codex_demo_payload_extracts_prefixed_fenced_json() -> None:
    payload = CodexDemoPayload.model_validate(_payload()).model_dump_json()
    raw = f"Here's a thinking process:\n<think>초안</think>\n```json\n{payload}\n```\ntrailing"
    parsed = _parse_payload(raw)
    assert parsed.slides[0].title == "A"
    assert parsed.voice_scripts[4].script_text == "e"


def test_codex_request_uses_modal_production_budget() -> None:
    req = _request(DemoGenerationInput(topic="회귀분석"), "statistics_inference")
    assert req.max_tokens == 16384
    assert req.temperature == 0.1
    assert req.extra == {}


def test_codex_prompt_contains_tutoring_blueprint() -> None:
    prompt = _user_prompt(DemoGenerationInput(topic="회귀분석과 p-value"), "statistics_inference")
    assert "과외 블루프린트" in prompt
    assert "변수·분포·추론·한계" in prompt
    assert "책 요약이 아니라 과외식" in prompt
    assert "적어도 7개 이상의 학습 문장" in prompt
    assert "작은 예시" in prompt
    assert "정답 근거와 대표 오답" in prompt
    assert "5~7문장" in prompt
    assert "데모 쇼케이스" in prompt
    assert "data-chart-spec" in prompt
    assert "mermaid 관계도" in prompt
    assert "기본 화면은 라이트모드" in prompt
    assert "후처리 공통 테마" in prompt
    assert "900자 이하" in prompt
    assert "metric-card" in prompt
    assert "토큰 색상" in prompt
    assert "assignment.assignment_format" in prompt
    assert "assignment.expected_minutes" in prompt
    assert "핵심 노트 3~5블록" in prompt
    assert "p.번호를 최소 4회" in prompt
    assert "assignment steps에는 p.번호를 최소 2회" in prompt


def test_codex_prompt_includes_reference_book_context_when_present() -> None:
    prompt = _user_prompt(
        DemoGenerationInput(
            topic="회귀분석",
            reference_book_context=ReferenceBookContext(
                source_title="회귀 교재",
                query="회귀분석 잔차",
                page_count=220,
                hits=[
                    ReferenceBookHit(
                        page=88,
                        snippet="잔차는 모델이 설명하지 못한 관측값과 예측값의 차이다.",
                        score=4.0,
                        source_title="회귀 교재",
                    )
                ],
            ),
        ),
        "statistics_inference",
    )

    assert "참고도서 발췌" in prompt
    assert "p.88" in prompt
    assert "발췌에 없는 내용" in prompt


def _payload() -> dict[str, object]:
    quiz = {
        "question": "Q",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "중",
        "explanation": "설명",
    }
    return {
        "slides": [
            {"slide_idx": 0, "title": "A", "focus": "개념", "checkpoint": "정의 가능?", "category": "text", "html": "<section>A</section>", "css": ""},
            {"slide_idx": 1, "title": "B", "focus": "실습", "checkpoint": "설명 가능?", "category": "interactive", "html": "<section>B</section>", "css": ""},
            {"slide_idx": 2, "title": "C", "focus": "코드", "checkpoint": "실행 가능?", "category": "code", "html": "<section>C</section>", "css": ""},
            {"slide_idx": 3, "title": "D", "focus": "확장", "checkpoint": "전이 가능?", "category": "text", "html": "<section>D</section>", "css": ""},
            {"slide_idx": 4, "title": "E", "focus": "점검", "checkpoint": "회상 가능?", "category": "interactive", "html": "<section>E</section>", "css": ""},
        ],
        "quizzes": [quiz, quiz, quiz, quiz, quiz],
        "note_blocks": [
            {"heading": "핵심", "bullets": ["a", "b"]},
            {"heading": "실습", "bullets": ["c", "d"]},
            {"heading": "복습", "bullets": ["e", "f"]},
        ],
        "assignment": {
            "title": "과제",
            "assignment_format": "서술형 복습지",
            "expected_minutes": 20,
            "steps": ["a", "b", "c"],
            "rubric": ["a", "b", "c"],
        },
        "voice_scripts": [
            {"slide_idx": 0, "script_text": "a"},
            {"slide_idx": 1, "script_text": "b"},
            {"slide_idx": 2, "script_text": "c"},
            {"slide_idx": 3, "script_text": "d"},
            {"slide_idx": 4, "script_text": "e"},
        ],
    }
