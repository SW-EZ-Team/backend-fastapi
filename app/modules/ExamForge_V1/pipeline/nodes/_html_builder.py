"""시험지/답안지 HTML 빌더 모듈."""
from __future__ import annotations

import html as _html
import re
from typing import Any

from app.modules.ExamForge_V1.common.errors import TemplateNotFoundError
from app.modules.ExamForge_V1.templates.catalog import get_template_spec
from app.modules.ExamForge_V1.templates.paper import (
    QuestionFrameSpec,
    question_frame,
    select_paper_template,
)

_EVENT_HANDLER_RE = re.compile(r"\bon[a-zA-Z]+\s*=")
_CHOICE_MARKERS = {
    "1": "①",
    "2": "②",
    "3": "③",
    "4": "④",
    "5": "⑤",
    "A": "A",
    "B": "B",
    "C": "C",
    "D": "D",
    "E": "E",
}
_LABELS = {
    "ko": {
        "lang": "ko",
        "default_title": "모의고사",
        "question_count": "문항 수",
        "time_limit": "제한 시간",
        "minutes": "분",
        "total_points": "총점",
        "passing_score": "합격 기준",
        "points": "점",
        "notice": "응시자 유의사항",
        "answer_sheet": "답안 기입란",
        "difficulty": "난이도",
        "blank_guide": "빈칸은 답안란에 순서대로 작성하시오.",
        "match_left": "좌측 항목",
        "match_right": "우측 설명",
        "blank_row": "빈칸",
        "sequence_instruction": "순서대로 기호를 적으시오.",
        "matching_instruction": "좌측 번호별 우측 기호를 쓰시오.",
        "answer_suffix": "답안 및 해설",
        "answer_copy": "채점자 확인용",
        "answer_key": "정답표",
        "no_questions": "문항 없음",
        "question_col": "문항",
        "answer_col": "정답",
        "correct_answer": "정답",
        "scoring_guide": "채점 기준",
        "distractor_design": "오답 설계",
        "source_ref": "근거",
    },
    "en": {
        "lang": "en",
        "default_title": "Practice Exam",
        "question_count": "Questions",
        "time_limit": "Time Limit",
        "minutes": "min",
        "total_points": "Total Points",
        "passing_score": "Passing Score",
        "points": "pts",
        "notice": "Candidate Instructions",
        "answer_sheet": "Answer Sheet",
        "difficulty": "Difficulty",
        "blank_guide": "Write blank answers in order in the answer area.",
        "match_left": "Left Item",
        "match_right": "Right Description",
        "blank_row": "Blank",
        "sequence_instruction": "Write item numbers in order.",
        "matching_instruction": "Write the right-side letter for each left-side item.",
        "answer_suffix": "Answer Key and Explanations",
        "answer_copy": "Instructor copy",
        "answer_key": "Answer Key",
        "no_questions": "No questions",
        "question_col": "Question",
        "answer_col": "Answer",
        "correct_answer": "Correct Answer",
        "scoring_guide": "Scoring Guide",
        "distractor_design": "Distractor Rationale",
        "source_ref": "Source",
    },
}


def build_exam_html(questions: list[dict], plan: dict) -> str:
    """시험지 HTML을 생성한다."""
    paper = select_paper_template(plan)
    title = plan.get("exam_title") or _label(paper.locale, "default_title")
    time_limit = _safe_int(plan.get("time_limit_minutes", 60), 60)
    total_points = _safe_float(plan.get("total_points", len(questions)), float(len(questions)))
    total_questions = _safe_int(plan.get("total_questions", len(questions)), len(questions))
    passing_score = _safe_float(plan.get("passing_score", 60.0), 60.0)

    lines = _build_exam_header(
        title=str(title),
        paper_name=paper.display_name,
        subtitle=paper.subtitle,
        time_limit=time_limit,
        total_points=total_points,
        total_questions=total_questions,
        passing_score=passing_score,
        examinee_fields=paper.examinee_fields,
        instructions=paper.instructions,
        locale=paper.locale,
    )

    for i, q in enumerate(questions, 1):
        lines.extend(_build_question_block(i, q, paper.locale))

    lines.extend([
        f"<footer class='exam-footer'>{_esc(paper.footer_note)}</footer>",
        "</main></body></html>",
    ])
    return "\n".join(lines)


def build_answers_html(questions: list[dict], plan: dict) -> str:
    """답안지 HTML을 생성한다."""
    paper = select_paper_template(plan)
    title = plan.get("exam_title") or _label(paper.locale, "default_title")
    lines = _build_answers_header(str(title), paper.display_name, paper.locale)
    lines.extend(_build_answer_key_table(questions, paper.locale))

    for i, q in enumerate(questions, 1):
        lines.extend(_build_answer_block(i, q, paper.locale))

    lines.extend([
        f"<footer class='exam-footer'>{_esc(paper.footer_note)}</footer>",
        "</main></body></html>",
    ])
    return "\n".join(lines)


def _esc(text: object) -> str:
    """사용자/LLM 유래 텍스트를 HTML-이스케이프한다 (XSS 방지)."""
    neutralized = _EVENT_HANDLER_RE.sub("data-removed=", str(text))
    return _html.escape(neutralized, quote=True)


def _build_exam_header(
    title: str,
    paper_name: str,
    subtitle: str,
    time_limit: int,
    total_points: float,
    total_questions: int,
    passing_score: float,
    examinee_fields: tuple[str, ...],
    instructions: tuple[str, ...],
    locale: str,
) -> list[str]:
    """시험지 HTML 헤더를 생성한다."""
    safe_title = _esc(title)
    total_points_text = _score_text(total_points)
    instruction_items = "".join(
        f"<li>{_esc(item)}</li>" for item in instructions
    )
    fields = "".join(
        f"<div class='field-cell'><span>{_esc(field)}</span><b></b></div>"
        for field in examinee_fields
    )
    return [
        "<!DOCTYPE html>",
        f"<html lang='{_label(locale, 'lang')}'><head><meta charset='UTF-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        f"<title>{safe_title}</title>",
        "<style>",
        _exam_css(),
        "</style></head><body><main class='paper exam-paper'>",
        "<section class='cover-head'>",
        f"<p class='paper-kicker'>{_esc(paper_name)} · {_esc(subtitle)}</p>",
        f"<h1>{safe_title}</h1>",
        "<div class='exam-stats'>",
        f"<span>{_label(locale, 'question_count')} <strong>{total_questions}</strong></span>",
        f"<span>{_label(locale, 'time_limit')} <strong>{time_limit}{_label(locale, 'minutes')}</strong></span>",
        f"<span>{_label(locale, 'total_points')} <strong>{total_points_text}{_label(locale, 'points')}</strong></span>",
        f"<span>{_label(locale, 'passing_score')} <strong>{passing_score:.0f}{_label(locale, 'points')}</strong></span>",
        "</div>",
        f"<div class='candidate-grid'>{fields}</div>",
        "</section>",
        f"<section class='notice-box'><h2>{_label(locale, 'notice')}</h2>",
        f"<ol>{instruction_items}</ol></section>",
        f"<section class='answer-card'><h2>{_label(locale, 'answer_sheet')}</h2>",
        f"{_build_answer_sheet_preview(total_questions)}",
        "</section>",
    ]


def _build_question_block(num: int, q: dict, locale: str) -> list[str]:
    """단일 문제 블록 HTML을 생성한다."""
    difficulty = q.get("difficulty", 3)
    points = _safe_float(q.get("points", 1.0), 1.0)
    display_name, _, action = _template_summary(q)
    frame = question_frame(str(q.get("template_id", "")))
    lines = [
        "<section class='question-block'>",
        "<div class='question-head'>",
        f"<div><span class='section-title'>{_esc(frame.section_title)}</span>",
        f"<h2>{num}. {_esc(frame.stem_label)}</h2></div>",
        "<div class='question-meta'>",
        f"<span>{_esc(display_name)}</span>",
        f"<span>{_score_text(points)}{_label(locale, 'points')}</span>",
        f"<span>{_label(locale, 'difficulty')} {difficulty}</span>",
        "</div></div>",
        f"<p class='question-instruction'>{_esc(frame.instruction)}</p>",
        f"<p class='question-stem'>{_esc(q.get('stem', ''))}</p>",
    ]
    if q.get("code_snippet"):
        lines.append(f"<pre><code>{_esc(q.get('code_snippet', ''))}</code></pre>")
    lines.extend(_build_question_body(q, locale))
    lines.extend(_build_answer_area(q, frame, action, locale))
    lines.append("</section>")
    return lines


def _build_question_body(q: dict, locale: str) -> list[str]:
    """문제 본문 선택지/정렬/매칭 HTML을 생성한다."""
    lines: list[str] = []
    if q.get("options"):
        lines.append("<ol class='option-list'>")
        for idx, option in enumerate(q.get("options", []), 1):
            label = _get(option, "label", str(idx))
            marker = _CHOICE_MARKERS.get(str(label), str(label))
            text = _get(option, "text", "")
            lines.append(
                "<li>"
                f"<span class='choice-marker'>{_esc(marker)}</span>"
                f"<span>{_esc(text)}</span>"
                "</li>"
            )
        lines.append("</ol>")
    if q.get("blank_positions"):
        lines.append(f"<div class='blank-guide'>{_label(locale, 'blank_guide')}</div>")
    if q.get("ordering_items"):
        lines.append("<ol class='ordered-items'>")
        for idx, item in enumerate(q.get("ordering_items", []), 1):
            lines.append(
                f"<li><span class='choice-marker'>{idx}</span>{_esc(item)}</li>"
            )
        lines.append("</ol>")
    if q.get("matching_pairs"):
        lines.append(
            "<table class='match-table'><tr>"
            f"<th>{_label(locale, 'match_left')}</th>"
            f"<th>{_label(locale, 'match_right')}</th></tr>"
        )
        for idx, pair in enumerate(q.get("matching_pairs", []), 1):
            lines.append(
                "<tr>"
                f"<td>{idx}. {_esc(_get(pair, 'left', ''))}</td>"
                f"<td>{_choice_alpha(idx)}. {_esc(_get(pair, 'right', ''))}</td>"
                "</tr>"
            )
        lines.append("</table>")
    return lines


def _build_answer_area(
    q: dict,
    frame: QuestionFrameSpec,
    action: str,
    locale: str,
) -> list[str]:
    """문항별 실제 시험지 답안 영역을 만든다."""
    space = frame.answer_space
    if space.startswith("omr-"):
        count = _safe_int(space.split("-")[-1], len(q.get("options") or []))
        markers = "".join(
            f"<span class='bubble'>{_CHOICE_MARKERS.get(str(i), str(i))}</span>"
            for i in range(1, max(1, count) + 1)
        )
        return [
            "<div class='answer-area choice-answer'>",
            f"<span>{_esc(frame.answer_label)}</span>{markers}",
            "</div>",
        ]
    if space == "true-false":
        true_marker, false_marker = ("T", "F") if locale == "en" else ("O", "X")
        return [
            "<div class='answer-area choice-answer'>",
            f"<span>{_esc(frame.answer_label)}</span>",
            f"<span class='bubble'>{true_marker}</span><span class='bubble'>{false_marker}</span>",
            "</div>",
        ]
    if space == "blank-table":
        rows = max(1, len(q.get("blank_positions") or [0]))
        cells = "".join(
            f"<tr><th>{_label(locale, 'blank_row')} {i}</th><td></td></tr>"
            for i in range(1, rows + 1)
        )
        return [
            "<div class='answer-area'>",
            f"<p>{_esc(frame.answer_label)} · {_esc(action)}</p>",
            f"<table class='answer-table'>{cells}</table>",
            "</div>",
        ]
    if space == "sequence-slots":
        count = max(3, len(q.get("ordering_items") or []))
        cells = "".join("<td></td>" for _ in range(count))
        return [
            "<div class='answer-area'>",
            f"<p>{_esc(frame.answer_label)} · {_label(locale, 'sequence_instruction')}</p>",
            f"<table class='sequence-table'><tr>{cells}</tr></table>",
            "</div>",
        ]
    if space == "matching-table":
        count = max(3, len(q.get("matching_pairs") or []))
        rows = "".join(
            f"<tr><th>{i}</th><td></td></tr>" for i in range(1, count + 1)
        )
        return [
            "<div class='answer-area'>",
            f"<p>{_esc(frame.answer_label)} · {_label(locale, 'matching_instruction')}</p>",
            f"<table class='answer-table compact'>{rows}</table>",
            "</div>",
        ]
    if space in ("ruled-box", "essay-sheet", "practical-box"):
        line_count = {"ruled-box": 6, "essay-sheet": 12, "practical-box": 5}[space]
        lines = "".join("<div class='ruled-line'></div>" for _ in range(line_count))
        return [
            "<div class='answer-area written-answer'>",
            f"<p>{_esc(frame.answer_label)} · {_esc(frame.scoring_rule)}</p>",
            lines,
            "</div>",
        ]
    return [
        "<div class='answer-area written-answer'>",
        f"<p>{_esc(frame.answer_label)} · {_esc(action)}</p>",
        "<div class='ruled-line'></div><div class='ruled-line'></div>",
        "</div>",
    ]


def _build_answers_header(title: str, paper_name: str, locale: str) -> list[str]:
    """답안지 HTML 헤더를 생성한다."""
    safe_title = _esc(title)
    return [
        "<!DOCTYPE html>",
        f"<html lang='{_label(locale, 'lang')}'><head><meta charset='UTF-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        f"<title>{safe_title} - {_label(locale, 'answer_suffix')}</title>",
        "<style>",
        _exam_css(),
        "</style></head><body><main class='paper answer-paper'>",
        "<section class='cover-head'>",
        f"<p class='paper-kicker'>{_esc(paper_name)} · {_label(locale, 'answer_copy')}</p>",
        f"<h1>{safe_title} - {_label(locale, 'answer_suffix')}</h1>",
        "</section>",
    ]


def _build_answer_key_table(questions: list[dict], locale: str) -> list[str]:
    """답안지 상단 요약표를 생성한다."""
    if not questions:
        return [
            "<section class='notice-box'>"
            f"<h2>{_label(locale, 'answer_key')}</h2>"
            f"<p>{_label(locale, 'no_questions')}</p></section>"
        ]
    rows = []
    for idx, q in enumerate(questions, 1):
        rows.append(
            "<tr>"
            f"<th>{idx}</th>"
            f"<td>{_esc(q.get('correct_answer', '-'))}</td>"
            f"<td>{_score_text(_safe_float(q.get('points', 1.0), 1.0))}{_label(locale, 'points')}</td>"
            "</tr>"
        )
    return [
        f"<section class='answer-key'><h2>{_label(locale, 'answer_key')}</h2>",
        "<table><tr>"
        f"<th>{_label(locale, 'question_col')}</th>"
        f"<th>{_label(locale, 'answer_col')}</th>"
        f"<th>{_label(locale, 'points')}</th></tr>",
        *rows,
        "</table></section>",
    ]


def _build_answer_block(num: int, q: dict, locale: str) -> list[str]:
    """단일 답안 블록 HTML을 생성한다."""
    display_name, _, _ = _template_summary(q)
    frame = question_frame(str(q.get("template_id", "")))
    lines = [
        "<section class='answer-block'>",
        "<div class='question-head'>",
        f"<h2>{num}. {_esc(display_name)}</h2>",
        f"<span class='section-title'>{_esc(frame.section_title)}</span>",
        "</div>",
        f"<p><strong>{_label(locale, 'correct_answer')}</strong> {_esc(q.get('correct_answer', '-'))}</p>",
        f"<p><strong>{_label(locale, 'scoring_guide')}</strong> {_esc(frame.scoring_rule)}</p>",
        f"<p class='explanation'>{_esc(q.get('explanation', ''))}</p>",
    ]
    if q.get("distractor_rationale"):
        lines.append(
            f"<p><strong>{_label(locale, 'distractor_design')}</strong> {_esc(q.get('distractor_rationale', ''))}</p>"
        )
    if q.get("source_reference"):
        lines.append(
            f"<p><small>{_label(locale, 'source_ref')}: {_esc(q.get('source_reference', ''))}</small></p>"
        )
    lines.append("</section>")
    return lines


def _build_answer_sheet_preview(total_questions: int) -> str:
    """시험지 첫 장 답안 기입란 요약을 만든다."""
    count = max(1, min(total_questions, 100))
    cells = []
    for idx in range(1, count + 1):
        cells.append(f"<span><b>{idx}</b> ① ② ③ ④ ⑤</span>")
    return "<div class='omr-grid'>" + "".join(cells) + "</div>"


def _template_summary(q: dict) -> tuple[str, str, str]:
    """문항의 템플릿 표시 정보를 반환한다."""
    template_id = q.get("template_id", "")
    try:
        spec = get_template_spec(template_id)
    except TemplateNotFoundError:
        return template_id or "기본형", "generic-card", "문항 요구에 맞게 답안 작성"
    return spec.display_name, spec.render_layout, spec.student_action


def _label(locale: str, key: str) -> str:
    """시험지 언어별 고정 라벨을 반환한다."""
    labels = _LABELS["en"] if str(locale).lower().startswith("en") else _LABELS["ko"]
    return labels[key]


def _exam_css() -> str:
    """시험지 공통 CSS를 반환한다."""
    return """
@page{size:A4;margin:16mm}
:root{--bg:#F2F4F1;--paper:#FFFDF8;--ink:#111;--muted:#4A4F4A;--line:#C9D3C7;--soft:#EEF6EE;--accent:#1F6F4A;--shade:#F7F8F4}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:'D2Coding','Noto Sans KR',Arial,sans-serif;line-height:1.62}
.paper{width:min(980px,100%);margin:24px auto;padding:34px 42px;background:var(--paper);border:1px solid var(--line);box-shadow:0 12px 28px rgba(0,0,0,.08)}
.cover-head{border:2px solid var(--ink);padding:18px 20px;margin-bottom:18px}
.paper-kicker{margin:0 0 6px;color:var(--muted);font-weight:700}
h1{margin:0;font-size:2rem;letter-spacing:0;text-align:center}
h2{margin:0;font-size:1.05rem;letter-spacing:0}
.exam-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin-top:16px;border:1px solid var(--ink)}
.exam-stats span{padding:9px;border-right:1px solid var(--ink);text-align:center}
.exam-stats span:last-child{border-right:0}
.candidate-grid{display:grid;grid-template-columns:repeat(4,1fr);margin-top:14px;border:1px solid var(--ink)}
.field-cell{min-height:48px;border-right:1px solid var(--ink);display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:end;padding:8px}
.field-cell:last-child{border-right:0}.field-cell span{font-weight:800}.field-cell b{border-bottom:1px solid var(--ink);height:18px}
.notice-box,.answer-card,.answer-key{border:1px solid var(--line);background:var(--shade);padding:16px;margin:18px 0}
.notice-box ol{margin:10px 0 0;padding-left:22px}.notice-box li{margin:4px 0}
.omr-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:10px}
.omr-grid span{border:1px solid var(--line);background:#fff;padding:6px 8px;white-space:nowrap}
.question-block,.answer-block{break-inside:avoid;border-top:2px solid var(--ink);padding:18px 0;margin:22px 0}
.question-head{display:flex;justify-content:space-between;gap:16px;align-items:start}
.section-title{display:inline-block;background:var(--soft);border:1px solid var(--line);padding:4px 8px;margin-bottom:8px;font-weight:800;color:var(--accent)}
.question-meta{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;min-width:210px}
.question-meta span{border:1px solid var(--line);background:#fff;padding:4px 8px;font-size:.86rem}
.question-instruction{margin:10px 0;color:var(--muted);font-weight:700}
.question-stem{font-size:1.02rem;margin:12px 0 14px;white-space:pre-wrap}
.option-list,.ordered-items{list-style:none;margin:12px 0;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:8px}
.option-list li,.ordered-items li{border:1px solid var(--line);background:#fff;padding:9px 10px;min-height:42px}
.choice-marker{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;margin-right:8px;border:1px solid var(--ink);border-radius:50%;font-weight:800}
pre{background:#202827;color:#FAFAF4;padding:14px;border-radius:4px;overflow-x:auto;border:1px solid #111}
code{font-family:'D2Coding',monospace}
table{width:100%;border-collapse:collapse;background:#fff;margin-top:10px}
th,td{border:1px solid var(--line);padding:9px;text-align:left;vertical-align:top}
.match-table th,.answer-table th{background:var(--soft)}
.blank-guide{border:1px dashed var(--line);padding:10px;background:#fff;margin:12px 0}
.answer-area{border:1px solid var(--ink);background:#fff;padding:12px;margin-top:14px}
.answer-area p{margin:0 0 8px;font-weight:800;color:var(--muted)}
.choice-answer{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.bubble{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border:1px solid var(--ink);border-radius:50%;font-weight:900;background:#fff}
.answer-table.compact{max-width:360px}.sequence-table td{height:42px;text-align:center}
.written-answer{min-height:120px}.ruled-line{height:30px;border-bottom:1px solid var(--line)}
.answer-key table{font-size:.95rem}.answer-block p{margin:8px 0}.explanation{white-space:pre-wrap}
.exam-footer{margin-top:28px;padding-top:14px;border-top:1px solid var(--line);text-align:center;color:var(--muted);font-weight:800}
@media print{body{background:#fff}.paper{box-shadow:none;border:0;margin:0;width:100%;padding:0}.question-block,.answer-block{page-break-inside:avoid}}
@media (max-width:760px){.paper{margin:0;padding:22px}.exam-stats,.candidate-grid,.omr-grid,.option-list,.ordered-items{grid-template-columns:1fr}.question-head{display:block}.question-meta{justify-content:flex-start}.field-cell{border-right:0;border-bottom:1px solid var(--ink)}}
"""


def _score_text(value: float) -> str:
    """점수 표기에서 불필요한 .0을 제거한다."""
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _safe_int(value: Any, default: int) -> int:
    """정수 변환 실패 시 기본값을 반환한다."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    """실수 변환 실패 시 기본값을 반환한다."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get(value: object, key: str, default: str) -> str:
    """dict/Pydantic 객체 양쪽에서 문자열 값을 읽는다."""
    if isinstance(value, dict):
        return str(value.get(key, default))
    return str(getattr(value, key, default))


def _choice_alpha(index: int) -> str:
    """1부터 시작하는 인덱스를 A, B, C...로 변환한다."""
    return chr(ord("A") + max(0, index - 1))
