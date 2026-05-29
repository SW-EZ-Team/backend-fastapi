"""Gemini CLI 프론트 보고서 렌더링 검증."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.modules.ExamForge_V1.test_runtime.frontend_report import (
    FrontendReportInput,
    build_frontend_report,
    json_text,
)
from app.modules.ExamForge_V1.test_runtime.gemini_cli_passthrough import GeminiCliCapture
from app.modules.ExamForge_V1.test_runtime.prompt_builder import build_exam_json_prompt
from app.modules.ExamForge_V1.test_runtime import run_gemini_cli_report
from app.modules.ExamForge_V1.test_runtime.run_gemini_cli_report import (
    _decode_json_object,
    _render,
)


def test_prompt_requests_json_only_with_source_material() -> None:
    """프롬프트는 자료 기반 JSON 객체만 요구한다."""
    prompt = build_exam_json_prompt(
        source_text="Rust 소유권 설명 " * 20,
        subject="Rust",
        total_questions=5,
    )

    assert "반드시 JSON 객체 하나만 출력" in prompt
    assert '"exam_plan"' in prompt
    assert "Rust 소유권 설명" in prompt


def test_render_uses_payload_without_fallback_exam() -> None:
    """파싱된 문항 데이터가 없으면 가짜 시험지를 만들지 않는다."""
    exam_html, answers_html = _render({})

    assert exam_html == ""
    assert answers_html == ""


def test_render_builds_exam_html_from_payload() -> None:
    """Gemini 응답 payload를 기존 ExamForge HTML 렌더러에 전달한다."""
    exam_html, answers_html = _render(_sample_payload())

    assert "Rust 실전 모의고사" in exam_html
    assert "답안 기입란" in exam_html
    assert "정답표" in answers_html
    assert "메모리 안전성" in answers_html


def test_frontend_report_uses_mock_exam_design_tokens() -> None:
    """보고서가 실제 프론트 MockExam 계열 토큰과 레이아웃을 사용한다."""
    capture = _capture()
    report = build_frontend_report(
        FrontendReportInput(
            capture=capture,
            parsed_json_text=json_text(_sample_payload()),
            exam_html="<main>시험지</main>",
            answers_html="<main>정답지</main>",
        )
    )

    assert "--page-max-w:1600px" in report
    assert "PRACTICAL MOCK EXAM" in report
    assert "class='layout'" in report
    assert "Gemini raw_response" in report
    assert "<main>시험지</main>" not in report
    assert "&lt;main&gt;시험지&lt;/main&gt;" in report


def test_decode_json_object_accepts_wrapped_text() -> None:
    """응답 앞뒤 설명이 있어도 첫 JSON 객체를 읽는다."""
    value = _decode_json_object("prefix\n{\"ok\": true}\nsuffix")

    assert value == {"ok": True}


async def test_run_preserves_raw_artifacts_when_render_fails(
    monkeypatch,
    tmp_path,
) -> None:
    """렌더링 실패가 나도 Gemini 원문 캡처 파일은 먼저 남긴다."""
    raw_response = json_text(_sample_payload())

    class FakeConnector:
        """실제 Gemini CLI를 호출하지 않는 커넥터."""

        def __init__(self, model: str | None = None) -> None:
            self.model = model

        async def capture(self, prompt: str, timeout_sec: int | None = None):
            return GeminiCliCapture(
                command=["gemini", "-p", "<prompt>"],
                model=self.model or "gemini-test",
                prompt=prompt,
                stdout='{"response":"ok"}',
                stderr="",
                returncode=0,
                raw_response=raw_response,
                started_at="2026-05-26T00:00:00Z",
                duration_sec=1.2,
            )

    def fail_render(_payload):
        raise ValueError("bad renderer payload")

    monkeypatch.setattr(run_gemini_cli_report, "GeminiCliPassthrough", FakeConnector)
    monkeypatch.setattr(run_gemini_cli_report, "_render", fail_render)

    report_path = await run_gemini_cli_report._run(
        SimpleNamespace(
            subject="Rust",
            source_file=None,
            total_questions=5,
            locale="ko",
            template_id="ko_multiple_choice_5",
            model="gemini-test",
            timeout_sec=30,
            output_dir=str(tmp_path),
        )
    )

    raw_files = list(tmp_path.glob("*_raw_response.txt"))
    assert raw_files
    assert raw_files[0].read_text(encoding="utf-8") == raw_response
    assert "ExamForge HTML 렌더링 실패" in Path(report_path).read_text(encoding="utf-8")


def _capture() -> GeminiCliCapture:
    """보고서 테스트용 캡처 객체."""
    return GeminiCliCapture(
        command=["gemini", "-p", "<prompt>"],
        model="gemini-2.5-flash",
        prompt="prompt",
        stdout='{"response":"{}"}',
        stderr="",
        returncode=0,
        raw_response="{}",
        started_at="2026-05-26T00:00:00Z",
        duration_sec=1.2,
    )


def _sample_payload() -> dict[str, object]:
    """렌더링 테스트용 최소 payload."""
    return {
        "exam_plan": {
            "exam_title": "Rust 실전 모의고사",
            "subject": "Rust",
            "total_questions": 5,
            "total_points": 10.0,
            "time_limit_minutes": 15,
            "locale": "ko",
            "category": "korean",
            "type_allocations": [{
                "template_id": "ko_multiple_choice_5",
                "count": 1,
                "difficulty_distribution": {3: 1},
                "points_per_question": 2.0,
            }],
            "topic_weights": {"소유권": 1.0},
            "passing_score": 60.0,
            "bloom_distribution": {"이해": 1.0},
        },
        "questions": [{
            "question_id": "q1",
            "draft_id": "d1",
            "template_id": "ko_multiple_choice_5",
            "topic": "소유권",
            "difficulty": 3,
            "bloom_level": "이해",
            "stem": "Rust 소유권의 핵심 목적은 무엇인가?",
            "options": [
                {"label": "1", "text": "메모리 안전성", "is_correct": True},
                {"label": "2", "text": "동적 타입", "is_correct": False},
                {"label": "3", "text": "런타임 GC", "is_correct": False},
                {"label": "4", "text": "전역 상태", "is_correct": False},
                {"label": "5", "text": "컴파일 생략", "is_correct": False},
            ],
            "correct_answer": "1",
            "explanation": "자료에 따르면 소유권은 메모리 안전성을 보장한다.",
            "source_reference": "소유권 설명",
            "points": 2.0,
        }],
    }
