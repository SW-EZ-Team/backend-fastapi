from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import html
import json
import os
import re
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _bootstrap_modal_profile() -> None:
    if os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET"):
        return
    config_path = Path.home() / ".modal.toml"
    if not config_path.exists():
        return
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    profile = os.environ.get("MODAL_PROFILE") or _active_modal_profile(data)
    if not profile:
        return
    section = data.get(profile)
    if not isinstance(section, dict):
        return
    token_id = section.get("token_id")
    token_secret = section.get("token_secret")
    if isinstance(token_id, str) and isinstance(token_secret, str):
        os.environ.setdefault("MODAL_TOKEN_ID", token_id)
        os.environ.setdefault("MODAL_TOKEN_SECRET", token_secret)


def _active_modal_profile(data: dict[str, object]) -> str:
    for name, section in data.items():
        if isinstance(section, dict) and section.get("active") is True:
            return name
    return ""


_bootstrap_modal_profile()

from app.modules.ChapterStudio_V1.ai_connectors.qwen27b_modal_connector import Qwen27BModalConnector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIResponse
from app.modules.ChapterStudio_V1.app.codex_demo_pipeline import (
    _assignment_dict,
    _parse_payload,
    _quiz_dict,
    _request,
    _slide_inputs,
    _voice_dict,
)
from app.modules.ChapterStudio_V1.app.demo_quality import quality_marks, storage_preview
from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput
from app.modules.ChapterStudio_V1.app.frontend_payload import iframe_srcdoc
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext, ReferenceBookHit
from app.modules.ChapterStudio_V1.app.study_templates import select_template
from app.modules.ChapterStudio_V1.app.tutor_blueprints import blueprint_for
from app.modules.ChapterStudio_V1.postprocess.pipeline import postprocess_all

DEFAULT_OCR_JSONL = ROOT.parent / "artifacts" / "real_pdf_ocr" / "paddleocr_ppv4_real_pdf_20260513_114226.jsonl"
REPORT_ROOT = ROOT / "artifacts" / "modal_quality"
PASS_SCORE = 95
_PAGE_REF_RE = re.compile(r"p\.?\s*(\d+)(?:\s*(?:~|-|–|—)\s*p?\.?\s*(\d+))?|페이지\s*(\d+)")
_ASSIGNMENT_ACTION_RE = re.compile(
    r"(작성|비교|계산|분류|점검|설명|표시|풀|분석|구축|처리|해석|선택|서술|확인|탐색|평가|도출|적용)"
)


async def main() -> None:
    args = _parse_args()
    started = time.perf_counter()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = REPORT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    data = _demo_input(args)
    selected = select_template(args.template, data.topic)
    blueprint = blueprint_for(selected.key)
    if args.raw_response:
        response = _response_from_raw(Path(args.raw_response), Path(args.raw_meta) if args.raw_meta else None)
    else:
        connector = Qwen27BModalConnector()
        request = _request(data, selected.key).model_copy(update={"max_tokens": args.max_tokens})
        response = await connector.generate(request)
    wall_sec = time.perf_counter() - started
    if args.raw_response and args.raw_meta:
        wall_sec = _raw_wall_sec(Path(args.raw_meta), wall_sec)

    _write_text(out_dir / "raw_response.txt", response.text)
    _write_json(
        out_dir / "response_meta.json",
        {
            "run_id": run_id,
            "model": response.model,
            "finish_reason": response.finish_reason,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "wall_sec": wall_sec,
            "template": selected.key,
            "topic": data.topic,
            "manual_correction": False,
        },
    )

    parse_error = ""
    result: dict[str, Any] | None = None
    payload_dump: dict[str, Any] | None = None
    warnings: list[str] = []
    try:
        payload = _parse_payload(response.text)
        payload_dump = payload.model_dump()
        processed = await postprocess_all(_slide_inputs(payload))
        warnings = [warning for item in processed for warning in item["warnings"]]
        notes = [{"heading": block.heading, "bullets": block.bullets} for block in payload.note_blocks]
        voices = [_voice_dict(script) for script in payload.voice_scripts]
        quizzes = [_quiz_dict(quiz) for quiz in payload.quizzes]
        result = {
            "topic": data.topic,
            "template_label": selected.label,
            "quality_marks": quality_marks(selected, blueprint),
            "slides": [
                {
                    "slide_idx": item["index"],
                    "title": payload.slides[item["index"]].title,
                    "focus": payload.slides[item["index"]].focus,
                    "checkpoint": payload.slides[item["index"]].checkpoint,
                    "category": item["category"],
                    "template_role": selected.frames[item["index"]].role,
                    "iframe_html": iframe_srcdoc(item["iframe_html"]),
                    "warnings": item["warnings"],
                }
                for item in processed
            ],
            "quizzes": quizzes,
            "note_blocks": notes,
            "assignment": _assignment_dict(payload.assignment),
            "voice_scripts": voices,
            "storage_preview": storage_preview(len(processed), len(quizzes), len(notes), len(voices)),
            "reference_pages": _reference_pages(data.reference_book_context),
        }
        _write_json(out_dir / "payload.json", payload_dump)
        _write_json(out_dir / "demo_result.json", result)
    except Exception as exc:  # noqa: BLE001 - 평가 리포트는 실패 원인을 HTML로 남긴다.
        parse_error = f"{type(exc).__name__}: {exc}"

    scorecard = _score(payload_dump, result, parse_error, warnings)
    _write_json(out_dir / "scorecard.json", scorecard)
    report_html = _report_html(
        run_id=run_id,
        response_meta={
            "model": response.model,
            "finish_reason": response.finish_reason,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "wall_sec": wall_sec,
        },
        scorecard=scorecard,
        result=result,
        raw_text=response.text,
        parse_error=parse_error,
        warnings=warnings,
    )
    _write_text(out_dir / "quality_report.html", report_html)
    print(out_dir / "quality_report.html")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Modal Qwen 원본 모델 산출물 품질 평가")
    parser.add_argument("--template", default="exam_focus")
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument("--ocr-jsonl", default=str(DEFAULT_OCR_JSONL))
    parser.add_argument("--raw-response", default="")
    parser.add_argument("--raw-meta", default="")
    return parser.parse_args()


def _response_from_raw(raw_path: Path, meta_path: Path | None) -> ChapterAIResponse:
    meta: dict[str, object] = {}
    if meta_path is not None and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return ChapterAIResponse(
        text=raw_path.read_text(encoding="utf-8"),
        model=str(meta.get("model", "Qwen/Qwen3.6-27B-FP8")),
        input_tokens=_int_meta(meta, "input_tokens"),
        output_tokens=_int_meta(meta, "output_tokens"),
        finish_reason=str(meta.get("finish_reason", "raw_replay")),
    )


def _int_meta(meta: dict[str, object], key: str) -> int:
    value = meta.get(key, 0)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _raw_wall_sec(meta_path: Path, fallback: float) -> float:
    if not meta_path.exists():
        return fallback
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        return fallback
    value = meta.get("wall_sec")
    return float(value) if isinstance(value, int | float) else fallback


def _demo_input(args: argparse.Namespace) -> DemoGenerationInput:
    return DemoGenerationInput(
        topic="빅데이터 분석기사 필기: 데이터 탐색, 모델링, 결과 해석을 시험 직전 관점으로 연결하기",
        source_mode="pdf",
        pdf_file_name="빅데이터 분석기사(필기).pdf",
        duration_days=14,
        depth="deep",
        teacher="owl",
        tone=64,
        pace=58,
        tutor_depth=72,
        socratic=68,
        audience_level="자격증 필기 준비생",
        learning_goal="키워드 암기보다 문제에서 판단 기준을 빠르게 떠올리는 것",
        weak_points="혼동행렬, 과대적합 방지, 전처리·모델링·해석 순서 연결",
        chapter_title="빅데이터 분석기사 필기 실전 연결 강의",
        chapter_brief="OCR 참고도서 페이지를 근거로 자주 출제되는 탐색, 모델링, 결과 해석 키워드를 하나의 판단 흐름으로 묶는다.",
        reference_book_context=_reference_context(Path(args.ocr_jsonl)),
    )


def _reference_context(path: Path) -> ReferenceBookContext:
    pages = _load_pages(path, {7, 8, 9, 15})
    hits = [
        ReferenceBookHit(
            page=7,
            snippet=pages.get(7, "정규화, 결측값 대체, 변수변환, 클래스 불균형, EDA가 출제 키워드로 제시된다."),
            score=0.96,
            source_title="빅데이터 분석기사(필기).pdf",
            matched_terms=["정규화", "결측값", "EDA"],
        ),
        ReferenceBookHit(
            page=8,
            snippet=pages.get(8, "회귀분석, 로지스틱 회귀분석, 의사결정나무, 배깅, 부스팅, 과대적합이 출제 키워드로 제시된다."),
            score=0.94,
            source_title="빅데이터 분석기사(필기).pdf",
            matched_terms=["회귀분석", "의사결정나무", "과대적합"],
        ),
        ReferenceBookHit(
            page=9,
            snippet=pages.get(9, "혼동행렬, 재현율, ROC, F1 Score, 교차검증, 과대적합 방지가 결과 해석 키워드로 제시된다."),
            score=0.95,
            source_title="빅데이터 분석기사(필기).pdf",
            matched_terms=["혼동행렬", "ROC", "F1"],
        ),
        ReferenceBookHit(
            page=15,
            snippet=pages.get(15, "평가지표, 교차검증, 유의성 검정, 적합도 검정, 매개변수 최적화, 최종모형 선정이 출제기준에 포함된다."),
            score=0.92,
            source_title="빅데이터 분석기사(필기).pdf",
            matched_terms=["평가지표", "교차검증", "최종모형"],
        ),
    ]
    return ReferenceBookContext(
        source_title="빅데이터 분석기사(필기).pdf",
        query="빅데이터 분석기사 필기 실전 연결",
        page_count=955,
        ocr_model="paddleocr_ppv4_real_pdf_20260513_114226",
        hits=hits,
    )


def _reference_pages(context: ReferenceBookContext | None) -> list[int]:
    if context is None:
        return []
    return sorted({hit.page for hit in context.hits})


def _load_pages(path: Path, page_numbers: set[int]) -> dict[int, str]:
    if not path.exists():
        return {}
    pages: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        page = int(row.get("page", 0))
        if page in page_numbers:
            pages[page] = _compact(str(row.get("text", "")))[:700]
    return pages


def _score(
    payload: dict[str, Any] | None,
    result: dict[str, Any] | None,
    parse_error: str,
    warnings: list[str],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    _add(items, "schema", "JSON 스키마·파싱", 15, 0 if parse_error else 15, parse_error or "파싱 성공")
    if payload is None or result is None:
        total = _total_score(items)
        return {"total": total, "pass": False, "items": items, "critical_failures": [parse_error]}

    slide_score, slide_note = _score_slides(payload, result)
    voice_score, voice_note = _score_voice(result)
    note_score, note_note = _score_notes(result)
    assignment_score, assignment_note = _score_assignment(result)
    quiz_score, quiz_note = _score_quizzes(result)
    ref_score, ref_note = _score_references(result)
    safety_score, safety_note = _score_safety(payload, result)
    visual_gate_score, visual_gate_note = _score_visual_gates(payload, result)
    lesson_contract_score, lesson_contract_note = _score_lesson_contract(result)
    post_score, post_note = _score_postprocess(warnings)
    _add(items, "slides", "시각 슬라이드 역할 적합성", 20, slide_score, slide_note)
    _add(items, "visual_gate", "슬라이드별 시각자료 게이트", 10, visual_gate_score, visual_gate_note)
    _add(items, "lesson_contract", "강의 산출물 계약", 10, lesson_contract_score, lesson_contract_note)
    _add(items, "voice", "음성대본 튜터링 품질", 15, voice_score, voice_note)
    _add(items, "notes", "암기노트 복습 가치", 15, note_score, note_note)
    _add(items, "assignment", "과제·루브릭 실전성", 10, assignment_score, assignment_note)
    _add(items, "quizzes", "퀴즈 평가 분리", 10, quiz_score, quiz_note)
    _add(items, "references", "참고도서 페이지 활용", 10, ref_score, ref_note)
    _add(items, "safety", "보안·렌더 계약", 10, safety_score, safety_note)
    _add(items, "postprocess", "후처리 경고", 5, post_score, post_note)

    critical = [
        item["label"]
        for item in items
        if item["score"] < item["max_score"] and item["key"] in {"schema", "visual_gate", "lesson_contract", "safety", "references", "postprocess"}
    ]
    total = _total_score(items)
    return {"total": total, "pass": total >= PASS_SCORE and not critical, "items": items, "critical_failures": critical}


def _score_slides(payload: dict[str, Any], result: dict[str, Any]) -> tuple[int, str]:
    slides = payload.get("slides", [])
    rendered = result.get("slides", [])
    categories = {str(slide.get("category")) for slide in slides}
    counts_ok = len(slides) == 5 and {int(slide.get("slide_idx", -1)) for slide in slides} == set(range(5))
    category_fit = len(categories & {"text", "diagram", "code", "math", "chart", "interactive"})
    sentence_ok = sum(_sentence_count(str(slide.get("html", ""))) >= 7 for slide in slides)
    structure_ok = sum(_has_learning_structure(str(slide.get("html", ""))) for slide in slides)
    rendered_html = "\n".join(str(slide.get("iframe_html", "")) for slide in rendered)
    rendered_body = _strip_style(rendered_html)
    special = sum(
        [
            "rendered-chart" in rendered_html or "data:image/png" in rendered_html,
            "mermaid" in rendered_html or "mermaid-fallback" in rendered_html,
            "<code" in rendered_body and "tok-" in rendered_body,
            "katex" in rendered_html or "formula" in rendered_html,
            "<details" in rendered_html or "interactive" in categories,
        ]
    )
    score = 0
    score += 4 if counts_ok else 0
    score += min(3, category_fit)
    score += min(4, sentence_ok)
    score += min(3, structure_ok)
    score += min(6, special + max(0, special - 2))
    note = f"카테고리 {sorted(categories)}, 문장충족 {sentence_ok}/5, 구조충족 {structure_ok}/5, 시각요소 {special}/5"
    return min(20, score), note


def _score_visual_gates(payload: dict[str, Any], result: dict[str, Any]) -> tuple[int, str]:
    del payload
    slides = sorted(result.get("slides", []), key=lambda slide: int(slide.get("slide_idx", -1)))
    by_idx = {int(slide.get("slide_idx", -1)): _strip_style(str(slide.get("iframe_html", ""))) for slide in slides}
    failures: list[str] = []
    if set(by_idx) != set(range(5)):
        failures.append("slide_idx 0~4가 정확히 한 번씩 존재하지 않음")
    per_slide_visual = sum(_has_meaningful_visual(html) for html in by_idx.values())
    if per_slide_visual != 5:
        failures.append(f"슬라이드별 시각 단서 {per_slide_visual}/5")
    slot_checks = [
        (0, _has_rendered_chart, "slide0 차트 렌더"),
        (1, _has_rendered_diagram, "slide1 다이어그램 렌더"),
        (2, _has_code_and_formula, "slide2 코드+수식 렌더"),
        (4, _has_details_activity, "slide4 실습 details"),
    ]
    passed_slots = 0
    for index, check, label in slot_checks:
        html_text = by_idx.get(index, "")
        if check(html_text):
            passed_slots += 1
        else:
            failures.append(label)
    raw_failures = sum(_has_raw_visual_source(html) for html in by_idx.values())
    if raw_failures:
        failures.append(f"렌더되지 않은 raw 시각 블록 {raw_failures}개")
    score = (2 if per_slide_visual == 5 else 0) + passed_slots * 2
    note = "PASS" if not failures else "; ".join(failures[:6])
    return min(10, score), note


def _strip_style(value: str) -> str:
    return re.sub(r"<style\b[^>]*>.*?</style>", "", value, flags=re.DOTALL | re.IGNORECASE)


def _has_meaningful_visual(value: str) -> bool:
    markers = (
        "rendered-chart", "data:image/png", "mermaid-fallback", "<svg", "code-card",
        "shiki-dual-theme", "formula", "<details", "metric-card", "flow-strip",
        "comparison-table", "timeline", "step-grid", "<table",
    )
    return any(marker in value for marker in markers)


def _has_rendered_chart(value: str) -> bool:
    return "rendered-chart" in value and "data:image/png" in value and "chart-box" not in value


def _has_rendered_diagram(value: str) -> bool:
    return ("mermaid-fallback" in value or "<svg" in value) and not _has_raw_mermaid(value)


def _has_code_and_formula(value: str) -> bool:
    has_colored_code = ("code-card" in value or "shiki-dual-theme" in value) and "tok-" in value
    return has_colored_code and "formula" in value


def _has_details_activity(value: str) -> bool:
    return "<details" in value


def _has_raw_visual_source(value: str) -> bool:
    return _has_raw_mermaid(value) or ("chart-box" in value and "rendered-chart" not in value)


def _has_raw_mermaid(value: str) -> bool:
    return bool(re.search(r"<pre\b[^>]*class=['\"][^'\"]*\bmermaid\b", value))


def _has_learning_structure(html: str) -> bool:
    markers = ("metric-card", "flow-strip", "comparison-table", "timeline", "step-grid", "<table")
    return html.count("<li") >= 2 or any(marker in html for marker in markers)


def _score_voice(result: dict[str, Any]) -> tuple[int, str]:
    scripts = result.get("voice_scripts", [])
    count_ok = len(scripts) == 5
    sentence_ok = sum(5 <= _sentence_count(str(item.get("script_text", ""))) <= 8 for item in scripts)
    ref_count = _count_refs([str(item.get("script_text", "")) for item in scripts])
    length_ok = sum(180 <= len(str(item.get("script_text", ""))) <= 760 for item in scripts)
    score = (4 if count_ok else 0) + min(5, sentence_ok) + min(3, ref_count) + min(3, length_ok)
    return min(15, score), f"대본 {len(scripts)}개, 5~8문장 {sentence_ok}/5, p.참조 {ref_count}, 길이충족 {length_ok}/5"


def _score_notes(result: dict[str, Any]) -> tuple[int, str]:
    notes = result.get("note_blocks", [])
    blocks_ok = 3 <= len(notes) <= 5
    bullets = [str(bullet) for block in notes for bullet in block.get("bullets", [])]
    depth_ok = sum(len(bullet) >= 55 for bullet in bullets)
    ref_count = _count_refs(bullets)
    ref_score = _block_anchor_score(ref_count, len(notes), 4)
    heading_ok = sum(bool(str(block.get("heading", "")).strip()) for block in notes)
    score = (3 if blocks_ok else 0) + min(5, depth_ok) + ref_score + min(3, heading_ok)
    return min(15, score), f"블록 {len(notes)}개, 깊이 bullet {depth_ok}, p.참조 {ref_count}, 제목 {heading_ok}"


def _score_assignment(result: dict[str, Any]) -> tuple[int, str]:
    assignment = result.get("assignment", {})
    steps = assignment.get("steps", [])
    rubric = assignment.get("rubric", [])
    assignment_format = str(assignment.get("assignment_format", "")).strip()
    expected_minutes = assignment.get("expected_minutes")
    ref_count = _count_refs([*map(str, steps), *map(str, rubric)])
    action_ok = sum(bool(_ASSIGNMENT_ACTION_RE.search(str(step))) for step in steps)
    format_ok = bool(assignment_format)
    time_ok = isinstance(expected_minutes, int) and 5 <= expected_minutes <= 90
    score = (
        (2 if 3 <= len(steps) <= 5 else 0)
        + (2 if 3 <= len(rubric) <= 5 else 0)
        + min(2, action_ok)
        + min(2, ref_count)
        + (1 if format_ok else 0)
        + (1 if time_ok else 0)
    )
    return min(10, score), (
        f"format={format_ok}, expected_minutes={expected_minutes}, steps {len(steps)}개, "
        f"rubric {len(rubric)}개, 행동동사 {action_ok}, p.참조 {ref_count}"
    )


def _score_lesson_contract(result: dict[str, Any]) -> tuple[int, str]:
    slides = result.get("slides", [])
    voices = result.get("voice_scripts", [])
    notes = result.get("note_blocks", [])
    assignment = result.get("assignment", {})
    failures: list[str] = []
    slide_idx = sorted(int(slide.get("slide_idx", -1)) for slide in slides)
    voice_idx = sorted(int(script.get("slide_idx", -1)) for script in voices)
    slides_ok = len(slides) == 5 and slide_idx == list(range(5)) and all(
        str(slide.get("iframe_html", "")).lstrip().startswith("<!DOCTYPE html>")
        and not str(slide.get("iframe_html", "")).lstrip().startswith("<iframe")
        for slide in slides
    )
    if not slides_ok:
        failures.append("슬라이드 HTML srcDoc 5개 계약 불충족")
    voice_ok = len(voices) == 5 and voice_idx == list(range(5)) and all(_is_tts_script(str(item.get("script_text", ""))) for item in voices)
    if not voice_ok:
        failures.append("TTS용 슬라이드별 대본 계약 불충족")
    notes_ok = 3 <= len(notes) <= 5 and all(
        str(block.get("heading", "")).strip()
        and 2 <= len(block.get("bullets", [])) <= 5
        and all(len(str(bullet).strip()) >= 20 for bullet in block.get("bullets", []))
        for block in notes
    )
    if not notes_ok:
        failures.append("핵심노트 블록 계약 불충족")
    assignment_ok = (
        bool(str(assignment.get("title", "")).strip())
        and bool(str(assignment.get("assignment_format", "")).strip())
        and isinstance(assignment.get("expected_minutes"), int)
        and 5 <= int(assignment.get("expected_minutes", 0)) <= 90
        and 3 <= len(assignment.get("steps", [])) <= 5
        and 3 <= len(assignment.get("rubric", [])) <= 5
    )
    if not assignment_ok:
        failures.append("과제 형식·시간·절차·루브릭 계약 불충족")
    storage_tables = {str(item.get("table", "")) for item in result.get("storage_preview", [])}
    storage_ok = {"chapter_studio.slide", "chapter_studio.note", "chapter_studio.assignment", "chapter_studio.voice_script", "chapter_studio.voice_script_queue"}.issubset(storage_tables)
    if not storage_ok:
        failures.append("저장 단위 매핑 계약 불충족")
    score = sum([slides_ok, voice_ok, notes_ok, assignment_ok, storage_ok]) * 2
    return score, "PASS" if not failures else "; ".join(failures)


def _is_tts_script(value: str) -> bool:
    return bool(value.strip()) and "<" not in value and ">" not in value and "```" not in value


def _score_quizzes(result: dict[str, Any]) -> tuple[int, str]:
    quizzes = result.get("quizzes", [])
    count_ok = len(quizzes) == 5
    choices_ok = sum(len(item.get("choices", [])) == 4 for item in quizzes)
    explanation_ok = sum(len(str(item.get("explanation", ""))) >= 80 for item in quizzes)
    difficulty_ok = len({str(item.get("difficulty")) for item in quizzes}) >= 2
    score = (2 if count_ok else 0) + min(3, choices_ok) + min(3, explanation_ok) + (2 if difficulty_ok else 0)
    return min(10, score), f"문항 {len(quizzes)}개, 선택지4개 {choices_ok}/5, 해설충분 {explanation_ok}/5"


def _score_references(result: dict[str, Any]) -> tuple[int, str]:
    notes = result.get("note_blocks", [])
    note_text = " ".join(str(bullet) for block in notes for bullet in block.get("bullets", []))
    voice_text = " ".join(str(item.get("script_text", "")) for item in result.get("voice_scripts", []))
    assignment_text = " ".join(map(str, result.get("assignment", {}).get("steps", [])))
    allowed_pages = {int(page) for page in result.get("reference_pages", []) if isinstance(page, int)}
    referenced_pages = _extract_ref_pages([note_text, voice_text, assignment_text])
    all_refs = _count_refs([note_text, voice_text, assignment_text])
    note_refs = _count_refs([note_text])
    voice_refs = _count_refs([voice_text])
    score = _block_anchor_score(note_refs, len(notes), 4) + min(4, voice_refs) + min(2, all_refs)
    unknown_pages = sorted(referenced_pages - allowed_pages) if allowed_pages else []
    if unknown_pages:
        score = min(score, 8)
    note = f"전체 p.참조 {all_refs}, 암기노트 {note_refs}, 음성대본 {voice_refs}"
    if allowed_pages:
        note += f", OCR페이지 {sorted(allowed_pages)}"
    if unknown_pages:
        note += f", 미검증 페이지 {unknown_pages}"
    return min(10, score), note


def _block_anchor_score(ref_count: int, block_count: int, max_score: int) -> int:
    """핵심정리 블록마다 참고 페이지 앵커가 있으면 만점으로 본다."""
    if block_count <= 0 or ref_count <= 0:
        return 0
    required_refs = min(max_score, block_count)
    if ref_count >= required_refs:
        return max_score
    return min(max_score - 1, ref_count)


def _score_safety(payload: dict[str, Any], result: dict[str, Any]) -> tuple[int, str]:
    raw_html = "\n".join(str(slide.get("html", "")) + "\n" + str(slide.get("css", "")) for slide in payload.get("slides", []))
    iframe_html = "\n".join(str(slide.get("iframe_html", "")) for slide in result.get("slides", []))
    has_script = bool(re.search(r"<\\s*script", raw_html, re.I))
    has_external = bool(re.search(r"https?://|//[a-z0-9.-]+", raw_html, re.I))
    has_fence = "```" in raw_html
    iframe_doc_ok = iframe_html.count("<!DOCTYPE html>") == 5 and "<iframe" not in iframe_html.lower()
    score = (3 if not has_script else 0) + (2 if not has_external else 0) + (2 if not has_fence else 0) + (3 if iframe_doc_ok else 0)
    return score, f"script={has_script}, external_url={has_external}, fence={has_fence}, iframe_doc={iframe_doc_ok}"


def _score_postprocess(warnings: list[str]) -> tuple[int, str]:
    if not warnings:
        return 5, "후처리 경고 없음"
    return max(0, 5 - len(warnings)), "; ".join(warnings[:5])


def _report_html(
    run_id: str,
    response_meta: dict[str, Any],
    scorecard: dict[str, Any],
    result: dict[str, Any] | None,
    raw_text: str,
    parse_error: str,
    warnings: list[str],
) -> str:
    badge = "PASS" if scorecard["pass"] else "FAIL"
    rows = "\n".join(
        f"<tr><td>{_h(item['label'])}</td><td><strong>{item['score']} / {item['max_score']}</strong></td><td>{_h(item['note'])}</td></tr>"
        for item in scorecard["items"]
    )
    slides = _slides_html(result)
    notes = _notes_html(result)
    voice = _voice_html(result)
    raw_preview = _h(raw_text[:2400])
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>ChapterStudio Modal Quality Report</title>
<style>
:root{{color-scheme:light dark;--report-bg:#F8F8F6;--report-paper:#FFFFFF;--report-ink:#182229;--report-muted:#607078;--report-line:#D9DED8}}
body{{margin:0;background:#F8F8F6;color:#182229;font-family:Inter,Pretendard,system-ui,-apple-system,sans-serif;line-height:1.55}}
body{{background:var(--report-bg);color:var(--report-ink)}}
main{{max-width:1180px;margin:0 auto;padding:28px}}
.top{{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:end;border-bottom:1px solid #D9DED8;padding-bottom:18px}}
h1{{margin:0;font-size:28px;letter-spacing:0}} h2{{margin:28px 0 12px;font-size:18px}} h3{{margin:0 0 8px;font-size:15px}}
.badge{{display:inline-grid;place-items:center;min-width:92px;height:46px;border-radius:8px;background:{'#207B4C' if scorecard['pass'] else '#A33A3A'};color:white;font-weight:800}}
.score{{font-size:44px;font-weight:900;color:#1F2A30}} .meta{{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}}
.chip{{padding:5px 9px;border:1px solid var(--report-line);border-radius:999px;background:var(--report-paper);color:#43525A;font-size:12px}}
table{{width:100%;border-collapse:collapse;background:var(--report-paper);border:1px solid var(--report-line);border-radius:8px;overflow:hidden}}
td,th{{border-bottom:1px solid #E6EAE6;padding:10px 12px;text-align:left;vertical-align:top}} tr:last-child td{{border-bottom:0}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}} .panel{{background:var(--report-paper);border:1px solid var(--report-line);border-radius:8px;padding:14px}}
.slide iframe{{width:100%;min-height:420px;border:1px solid #CFD8CF;border-radius:8px;background:white}}
.fail{{border-left:4px solid #A33A3A}} .warn{{color:#7A6518}} pre{{white-space:pre-wrap;background:#172026;color:#F8F8F6;padding:12px;border-radius:8px;max-height:360px;overflow:auto}}
ul{{padding-left:20px}} .small{{color:#607078;font-size:13px}} .no-correction{{background:#FFF3DA;border:1px solid #E5D7AF;border-radius:8px;padding:10px 12px}}
@media(max-width:820px){{main{{padding:16px}}.top,.grid{{grid-template-columns:1fr}}}}
@media(prefers-color-scheme:dark){{:root{{--report-bg:#12191E;--report-paper:#192228;--report-ink:#EEF2F5;--report-muted:#B6C0C6;--report-line:#33434B}}.chip{{color:var(--report-muted)}}pre{{background:#0F1519;color:#EEF2F5}}td,th{{border-bottom-color:#28363D}}}}
</style>
</head>
<body><main>
<section class="top">
  <div>
    <h1>Modal GPU 원본 모델 품질 리포트</h1>
    <div class="meta">
      <span class="chip">run {run_id}</span>
      <span class="chip">{_h(str(response_meta['model']))}</span>
      <span class="chip">finish: {_h(str(response_meta['finish_reason']))}</span>
      <span class="chip">latency: {response_meta['wall_sec']:.1f}s</span>
      <span class="chip">tokens: {response_meta['input_tokens']} → {response_meta['output_tokens']}</span>
    </div>
  </div>
  <div><div class="badge">{badge}</div><div class="score">{scorecard['total']}</div></div>
</section>
<p class="no-correction">평가 원칙: 모델 응답 원문을 직접 보정하지 않았고, 파싱·후처리·채점 결과를 그대로 기록했다.</p>
{f'<p class="panel fail"><strong>파싱 실패:</strong> {_h(parse_error)}</p>' if parse_error else ''}
{f'<p class="panel warn"><strong>후처리 경고:</strong> {_h("; ".join(warnings))}</p>' if warnings else ''}
<h2>역할별 점수</h2>
<table><thead><tr><th>영역</th><th>점수</th><th>근거</th></tr></thead><tbody>{rows}</tbody></table>
{slides}
{notes}
{voice}
<h2>원본 응답 미리보기</h2>
<pre>{raw_preview}</pre>
</main></body></html>"""


def _slides_html(result: dict[str, Any] | None) -> str:
    if result is None:
        return ""
    blocks = []
    for slide in result.get("slides", []):
        blocks.append(
            f"""<article class="panel slide">
<h3>{slide['slide_idx']}. {_h(str(slide['title']))} <span class="small">({_h(str(slide['category']))})</span></h3>
{slide['iframe_html']}
<p class="small">{_h(str(slide['focus']))} · {_h(str(slide['checkpoint']))}</p>
</article>"""
        )
    return "<h2>슬라이드 렌더 미리보기</h2><section class=\"grid\">" + "\n".join(blocks) + "</section>"


def _notes_html(result: dict[str, Any] | None) -> str:
    if result is None:
        return ""
    note_blocks = []
    for block in result.get("note_blocks", []):
        bullets = "".join(f"<li>{_h(str(bullet))}</li>" for bullet in block.get("bullets", []))
        note_blocks.append(f"<article class=\"panel\"><h3>{_h(str(block.get('heading', '')))}</h3><ul>{bullets}</ul></article>")
    assignment = result.get("assignment", {})
    steps = "".join(f"<li>{_h(str(step))}</li>" for step in assignment.get("steps", []))
    rubric = "".join(f"<li>{_h(str(item))}</li>" for item in assignment.get("rubric", []))
    assignment_format = _h(str(assignment.get("assignment_format", "형식 미지정")))
    expected_minutes = _h(str(assignment.get("expected_minutes", "시간 미지정")))
    return (
        "<h2>암기노트·과제</h2><section class=\"grid\">"
        + "\n".join(note_blocks)
        + f"<article class=\"panel\"><h3>{_h(str(assignment.get('title', '과제')))}</h3>"
        + f"<p class=\"small\">형식: {assignment_format} · 예상 {expected_minutes}분</p>"
        + f"<ol>{steps}</ol><h3>루브릭</h3><ul>{rubric}</ul></article></section>"
    )


def _voice_html(result: dict[str, Any] | None) -> str:
    if result is None:
        return ""
    items = "".join(
        f"<article class=\"panel\"><h3>slide {item.get('slide_idx')}</h3><p>{_h(str(item.get('script_text', '')))}</p></article>"
        for item in result.get("voice_scripts", [])
    )
    return f"<h2>음성대본</h2><section class=\"grid\">{items}</section>"


def _add(items: list[dict[str, Any]], key: str, label: str, max_score: int, score: int, note: str) -> None:
    items.append({"key": key, "label": label, "max_score": max_score, "score": max(0, min(max_score, score)), "note": note})


def _total_score(items: list[dict[str, Any]]) -> int:
    max_score = sum(int(item["max_score"]) for item in items)
    if max_score == 0:
        return 0
    raw_score = sum(int(item["score"]) for item in items)
    return round(raw_score * 100 / max_score)


def _count_refs(values: list[str]) -> int:
    text = " ".join(values)
    count = 0
    for match in _PAGE_REF_RE.finditer(text):
        count += len(_pages_from_match(match))
    return count


def _extract_ref_pages(values: list[str]) -> set[int]:
    text = " ".join(values)
    pages: set[int] = set()
    for match in _PAGE_REF_RE.finditer(text):
        pages.update(_pages_from_match(match))
    return pages


def _pages_from_match(match: re.Match[str]) -> list[int]:
    start_raw, end_raw, page_raw = match.groups()
    if page_raw is not None:
        return [int(page_raw)]
    if start_raw is None:
        return []
    start = int(start_raw)
    end = int(end_raw) if end_raw is not None else start
    lower = min(start, end)
    upper = max(start, end)
    return list(range(lower, min(upper, lower + 19) + 1))


def _sentence_count(text: str) -> int:
    return len([part for part in re.split(r"[.!?。！？]|다\\.|요\\.|니다\\.", _plain(text)) if part.strip()])


def _plain(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def _h(value: str) -> str:
    return html.escape(value, quote=True)


if __name__ == "__main__":
    asyncio.run(main())
