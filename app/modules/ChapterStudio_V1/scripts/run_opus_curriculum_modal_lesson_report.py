from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import html
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_connectors.errors import ConnectorError
from app.curriculum_preview import build_curriculum_preview
from app.curriculum_preview_types import CurriculumLesson, CurriculumPreview, CurriculumPreviewRequest
from app.generation_context import GenerationContext

REPORT_ROOT = ROOT / "artifacts" / "curriculum_lesson_actual"


async def main() -> None:
    args = _parse_args()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = REPORT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    curriculum: CurriculumPreview | None = None
    context: GenerationContext | None = None
    lesson_reports: dict[str, str] = {}
    error = ""

    try:
        req = CurriculumPreviewRequest(
            title=args.title,
            topic=args.topic,
            subject=args.subject,
            difficulty=args.difficulty,
            lesson_count=args.lesson_count,
            teacher=args.teacher,
            engine=args.curriculum_engine,
        )
        curriculum = await build_curriculum_preview(req)
        _write_json(out_dir / "curriculum_preview.json", curriculum.model_dump(mode="json"))
        lesson = _select_lesson(curriculum, args.lesson_order)
        context = _generation_context_from_lesson(
            curriculum,
            lesson,
            curriculum_engine=args.curriculum_engine,
            topic=args.topic,
            weak_points=args.weak_points,
            slide_count=args.slide_count,
            difficulty=args.difficulty,
            teacher=args.teacher,
        )
        context_path = out_dir / "generation_context.json"
        _write_json(context_path, context.model_dump(mode="json"))
        if args.generate_lesson:
            lesson_reports = _run_modal_lesson_generation(
                context_path,
                slide_count=args.slide_count,
                expand_voice=args.expand_voice,
                seed=args.seed,
            )
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, ConnectorError):
            error = f"{error} (커넥터 계층에서 중단)"

    wall_sec = time.perf_counter() - started
    report = _report_html(
        run_id,
        wall_sec=wall_sec,
        curriculum=curriculum,
        context=context,
        lesson_reports=lesson_reports,
        curriculum_engine=args.curriculum_engine,
        error=error,
    )
    report_path = out_dir / "curriculum_lesson_report.html"
    _write_text(report_path, report)
    print(report_path)
    if error:
        raise SystemExit(2)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="커리큘럼 5강 + Modal 실제 강의 1개 통합 보고서")
    parser.add_argument("--curriculum-engine", default="codex_cli", choices=("codex_cli", "opus46"), help="운영은 opus46, 이번 실전 테스트는 codex_cli OAuth 우회")
    parser.add_argument("--title", default="Rust 언어 5강 실전 과외 커리큘럼")
    parser.add_argument("--topic", default="Rust 언어 기초: 소유권, 빌림, 라이프타임, 에러 읽기")
    parser.add_argument("--subject", default="프로그래밍")
    parser.add_argument("--difficulty", default="medium", choices=("easy", "medium", "hard"))
    parser.add_argument("--lesson-count", type=int, default=5, choices=range(5, 16))
    parser.add_argument("--lesson-order", type=int, default=1, choices=range(1, 16))
    parser.add_argument("--slide-count", type=int, default=15, choices=range(10, 16))
    parser.add_argument("--teacher", default="owl", choices=("owl", "cat", "fox", "bear"))
    parser.add_argument(
        "--weak-points",
        default="소유권 이동, 빌림 규칙, 가변 참조, 라이프타임, 컴파일 에러 읽기",
    )
    parser.add_argument("--seed", type=int, default=71)
    parser.add_argument("--generate-lesson", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--expand-voice", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def _select_lesson(curriculum: CurriculumPreview, order: int) -> CurriculumLesson:
    for lesson in curriculum.lessons:
        if lesson.order == order:
            return lesson
    raise ValueError(f"{order}강을 커리큘럼에서 찾지 못했다.")


def _generation_context_from_lesson(
    curriculum: CurriculumPreview,
    lesson: CurriculumLesson,
    *,
    curriculum_engine: str,
    topic: str,
    weak_points: str,
    slide_count: int,
    difficulty: str,
    teacher: str,
) -> GenerationContext:
    depth = {"easy": "basic", "medium": "normal", "hard": "deep"}[difficulty]
    return GenerationContext(
        lesson_id=f"lesson-{curriculum_engine}-{lesson.order:02d}",
        tutoring_id=curriculum.tutoring_id,
        user_id="user-local-actual-test",
        curriculum_plan_id=f"{curriculum.tutoring_id}-plan-{curriculum_engine}",
        topic=f"{topic} / {lesson.title}",
        source_mode="topic",
        pdf_file_name="",
        duration_days=30,
        depth=depth,
        teacher=teacher,
        tone=62,
        pace=44,
        tutor_depth=82,
        socratic=72,
        audience_level="Python은 써봤지만 Rust의 소유권, 빌림, 라이프타임과 컴파일 에러 읽기가 약한 학습자",
        learning_goal=_clip(lesson.description, 160),
        weak_points=_clip(weak_points, 240),
        chapter_title=_clip(lesson.title, 120),
        chapter_brief=_clip(lesson.description, 400),
        template="auto",
        slide_count=slide_count,
        reference_book_context=None,
    )


def _run_modal_lesson_generation(
    context_path: Path,
    *,
    slide_count: int,
    expand_voice: bool,
    seed: int,
) -> dict[str, str]:
    cmd = [
        "uv",
        "run",
        "python",
        "scripts/run_modal_actual_lesson_eval.py",
        "--generation-context-json",
        str(context_path),
        "--slide-count",
        str(slide_count),
        "--parallel-slides",
        "--max-tokens",
        "32000",
        "--temperature",
        "0.1",
        "--seed",
        str(seed),
    ]
    if expand_voice:
        cmd.append("--expand-voice")
    try:
        completed = subprocess.run(cmd, cwd=ROOT, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stdout = (exc.stdout or "").strip()
        stderr = (exc.stderr or "").strip()
        detail = [
            f"Modal lesson generation failed with exit={exc.returncode}.",
            "Command: " + " ".join(cmd),
        ]
        if stdout:
            detail.append("STDOUT:\n" + stdout[-8000:])
        if stderr:
            detail.append("STDERR:\n" + stderr[-8000:])
        raise RuntimeError("\n\n".join(detail)) from exc
    paths = [line.strip() for line in completed.stdout.splitlines() if line.strip().endswith(".html")]
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "quality_report": paths[0] if paths else "",
        "practical_report": paths[1] if len(paths) > 1 else "",
    }


def _report_html(
    run_id: str,
    *,
    wall_sec: float,
    curriculum: CurriculumPreview | None,
    context: GenerationContext | None,
    lesson_reports: dict[str, str],
    curriculum_engine: str,
    error: str,
) -> str:
    status = "FAIL" if error else "PASS"
    badge_color = "#A33A3A" if error else "#207B4C"
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>커리큘럼 + Modal 강의 실전 보고서</title>
<style>
:root{{color-scheme:light dark;--bg:#F8F8F6;--paper:#FFFDF7;--ink:#172229;--muted:#52646F;--line:#D7E0DA;--accent:#207B4C;--accent2:#2A5C7A}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,Pretendard,system-ui,-apple-system,sans-serif;line-height:1.6}}
main{{max-width:1280px;margin:0 auto;padding:30px}} h1{{margin:0;font-size:30px}} h2{{margin:30px 0 12px;font-size:21px}} h3{{margin:0 0 8px}}
.hero{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:18px;align-items:end;padding:24px;border:1px solid var(--line);border-radius:8px;background:linear-gradient(135deg,var(--paper),#EAF2F7)}}
.badge{{display:inline-grid;place-items:center;min-width:96px;height:48px;border-radius:8px;background:{badge_color};color:white;font-weight:900}} .score{{font-size:42px;font-weight:900;text-align:right}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}} .chip{{padding:6px 10px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.72);font-size:12px;font-weight:700}}
.panel{{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:16px;box-shadow:0 8px 20px rgba(23,34,41,.06)}} .grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
table{{width:100%;border-collapse:collapse;background:white;border:1px solid var(--line);border-radius:8px;overflow:hidden}} td,th{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} tr:last-child td{{border-bottom:0}}
iframe{{width:100%;min-height:720px;border:1px solid #BFD0C4;border-radius:8px;background:#fff}} .small{{color:var(--muted);font-size:13px}} .fail{{color:#9A2F2F;font-weight:800;white-space:pre-wrap}}
@media(max-width:920px){{main{{padding:16px}}.hero,.grid{{grid-template-columns:1fr}}iframe{{min-height:520px}}}}
@media(prefers-color-scheme:dark){{:root{{--bg:#12191E;--paper:#182229;--ink:#F1F5F3;--muted:#B9C5CC;--line:#32444C}}table{{background:#10181D;color:var(--ink)}}}}
</style>
</head>
<body><main>
<section class="hero"><div><h1>커리큘럼 + Modal 실제 강의 보고서</h1>
<div class="chips"><span class="chip">run {run_id}</span><span class="chip">curriculum {_h(_engine_label(curriculum_engine))}</span><span class="chip">lesson Modal Qwen B200</span><span class="chip">wall {wall_sec:.1f}s</span></div>
<p>평가 원칙: 운영 설계는 Claude Opus API Planner이며, 이번 테스트는 커리큘럼 단계만 Codex CLI OAuth로 우회할 수 있다. 강의 본문은 Modal 병렬 슬라이드 생성 경로를 사용한다. 모델 응답 원문을 사람이 직접 보정하지 않는다.</p></div><div><div class="badge">{status}</div><div class="score">{status}</div></div></section>
{_error_html(error)}
{_curriculum_html(curriculum)}
{_context_html(context)}
{_lesson_report_html(lesson_reports)}
</main></body></html>"""


def _error_html(error: str) -> str:
    if not error:
        return ""
    return f"<h2>실행 중단</h2><section class=\"panel\"><p class=\"fail\">{_h(error)}</p><p>커리큘럼 생성 엔진과 Modal 하위 호출의 stdout/stderr를 확인해야 한다. 정적 결과로 대체하지 않는다.</p></section>"


def _engine_label(engine: str) -> str:
    if engine == "opus46":
        return "Claude Opus 4.6 API"
    return "Codex CLI OAuth"


def _curriculum_html(curriculum: CurriculumPreview | None) -> str:
    if curriculum is None:
        return ""
    rows = []
    for lesson in curriculum.lessons:
        rows.append(
            "<tr>"
            f"<td>{lesson.order}</td><td>{_h(lesson.title)}</td><td>{_h(lesson.description)}</td>"
            f"<td>{lesson.slide_count}</td><td>{lesson.estimated_minutes}분</td>"
            f"<td>{_h(', '.join(lesson.key_topics))}</td>"
            "</tr>"
        )
    return (
        "<h2>5강 커리큘럼</h2><section class=\"panel\">"
        f"<p><strong>{_h(curriculum.title)}</strong> · 총 {curriculum.estimated_total_minutes}분 · 상태 {curriculum.status}</p>"
        "<table><thead><tr><th>강</th><th>제목</th><th>설명</th><th>슬라이드</th><th>예상</th><th>핵심 주제</th></tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table></section>"
    )


def _context_html(context: GenerationContext | None) -> str:
    if context is None:
        return ""
    return f"""<h2>선택 강의 생성 입력</h2><section class="grid">
<article class="panel"><h3>DB generation_context 형식</h3><p><strong>lesson_id:</strong> {_h(context.lesson_id)}</p><p><strong>chapter:</strong> {_h(context.chapter_title)}</p><p><strong>slide_count:</strong> {context.slide_count}</p></article>
<article class="panel"><h3>학습자 맞춤</h3><p>{_h(context.audience_level)}</p><p><strong>약점:</strong> {_h(context.weak_points)}</p></article>
</section>"""


def _lesson_report_html(lesson_reports: dict[str, str]) -> str:
    practical = lesson_reports.get("practical_report", "")
    quality = lesson_reports.get("quality_report", "")
    if not practical and not quality:
        return ""
    links = []
    if practical:
        links.append(f"<a href=\"{Path(practical).as_uri()}\">실전 산출물 보고서</a>")
    if quality:
        links.append(f"<a href=\"{Path(quality).as_uri()}\">품질·비용 보고서</a>")
    iframe = f"<iframe src=\"{Path(practical).as_uri()}\"></iframe>" if practical else ""
    return "<h2>생성된 강의 전체 산출물</h2><section class=\"panel\"><p>" + " · ".join(links) + "</p>" + iframe + "</section>"


def _clip(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def _h(value: str) -> str:
    return html.escape(value, quote=True)


if __name__ == "__main__":
    asyncio.run(main())
