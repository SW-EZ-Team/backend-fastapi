"""Gemini CLI 원문과 프론트 표시 결과 HTML 보고서 생성기."""
from __future__ import annotations

import html
import json
from dataclasses import dataclass

from app.modules.ExamForge_V1.test_runtime.gemini_cli_passthrough import GeminiCliCapture
from app.modules.ExamForge_V1.test_runtime.report_styles import frontend_report_css


@dataclass(frozen=True)
class FrontendReportInput:
    """보고서 렌더링 입력."""

    capture: GeminiCliCapture
    parsed_json_text: str
    exam_html: str
    answers_html: str
    parse_error: str | None = None
    report_title: str = "AI 모의고사 Gemini CLI 실응답 보고서"


def build_frontend_report(data: FrontendReportInput) -> str:
    """frontend-web MockExam 디자인 규칙을 반영한 단일 HTML을 생성한다."""
    status = "성공" if data.capture.returncode == 0 and data.parse_error is None else "확인 필요"
    raw_response = data.capture.raw_response or data.capture.stdout
    return "\n".join([
        "<!doctype html>",
        "<html lang='ko'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        f"<title>{_esc(data.report_title)}</title>",
        f"<style>{frontend_report_css()}</style></head><body>",
        "<main class='page'>",
        _intro(data.report_title),
        "<section class='layout'>",
        "<div class='main'>",
        _summary_section(data, status),
        _iframe_section("실제 프론트 표시 시험지", data.exam_html),
        _iframe_section("실제 프론트 표시 정답지", data.answers_html),
        _raw_section("Gemini raw_response", raw_response),
        _raw_section("파싱된 JSON", data.parsed_json_text),
        "</div>",
        _aside(data, status),
        "</section></main></body></html>",
    ])


def _intro(title: str) -> str:
    """프론트 PageIntro 구조를 정적 HTML로 재현한다."""
    return (
        "<div class='intro'><div>"
        "<div class='eyebrow'>PRACTICAL MOCK EXAM · GEMINI CLI</div>"
        f"<div class='title'><span class='script'>실전</span>{_esc(title)}</div>"
        "<div class='desc'>Gemini CLI가 돌려준 원본 응답과 ExamForge 렌더러가 실제로 보여주는 HTML을 함께 보존합니다.</div>"
        "</div></div>"
    )


def _summary_section(data: FrontendReportInput, status: str) -> str:
    """상단 요약 카드."""
    warning = ""
    if data.parse_error:
        warning = f"<div class='warn'>{_esc(data.parse_error)}</div>"
    return (
        "<section class='section'><div class='section-head'>"
        "<div><div class='section-title'>실행 요약</div>"
        "<div class='section-desc'>운영 모델을 바꾸지 않는 테스트 전용 캡처입니다.</div></div>"
        f"<span class='badge'>{_esc(status)}</span></div><div class='body'>"
        "<div class='metric-grid'>"
        f"{_metric('모델', data.capture.model)}"
        f"{_metric('종료 코드', data.capture.returncode)}"
        f"{_metric('소요 시간', f'{data.capture.duration_sec:.3f}s')}"
        f"{_metric('시작 시각', data.capture.started_at)}"
        "</div>"
        f"{warning}"
        "</div></section>"
    )


def _iframe_section(title: str, body: str) -> str:
    """프론트 결과 HTML을 iframe srcdoc으로 그대로 표시한다."""
    if not body:
        content = "<div class='warn'>렌더링할 HTML이 없습니다.</div>"
    else:
        content = f"<iframe class='frame' srcdoc=\"{_attr(body)}\"></iframe>"
    return (
        "<section class='section'><div class='section-head'>"
        f"<div><div class='section-title'>{_esc(title)}</div>"
        "<div class='section-desc'>ExamForge HTML 렌더러의 결과를 iframe에 그대로 넣었습니다.</div></div>"
        "</div><div class='body'>"
        f"{content}</div></section>"
    )


def _raw_section(title: str, text: str) -> str:
    """원문 텍스트 섹션."""
    return (
        "<section class='section'><div class='section-head'>"
        f"<div><div class='section-title'>{_esc(title)}</div>"
        "<div class='section-desc'>내용은 수정하지 않고 HTML escape만 적용했습니다.</div></div>"
        "</div><div class='body'>"
        f"<pre class='raw'>{_esc(text)}</pre></div></section>"
    )


def _aside(data: FrontendReportInput, status: str) -> str:
    """MockExamAside와 같은 보조 패널."""
    command = " ".join(data.capture.command)
    return (
        "<aside class='aside'>"
        "<div class='inspector'><div class='inspector-title'>응답 기록</div>"
        "<div class='inspector-body'>"
        f"{_metric('상태', status)}{_metric('stdout', f'{len(data.capture.stdout)} chars')}"
        f"{_metric('stderr', f'{len(data.capture.stderr)} chars')}"
        "</div></div>"
        "<div class='inspector'><div class='inspector-title'>실행 명령</div>"
        f"<div class='inspector-body'><pre class='raw'>{_esc(command)}</pre></div></div>"
        "</aside>"
    )


def _metric(key: str, value: object) -> str:
    """InfoBox 패턴의 단일 지표."""
    return (
        "<div class='metric'>"
        f"<div class='metric-k'>{_esc(key)}</div>"
        f"<div class='metric-v'>{_esc(value)}</div>"
        "</div>"
    )


def json_text(value: object) -> str:
    """보고서용 JSON 문자열을 만든다."""
    return json.dumps(value, ensure_ascii=False, indent=2)


def _esc(value: object) -> str:
    """HTML 본문 escape."""
    return html.escape(str(value), quote=False)


def _attr(value: object) -> str:
    """HTML 속성 escape."""
    return html.escape(str(value), quote=True)
