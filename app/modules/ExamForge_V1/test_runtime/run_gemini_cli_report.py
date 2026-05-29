"""Gemini CLI 실응답으로 ExamForge HTML 보고서를 생성하는 스크립트."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from app.modules.ExamForge_V1.pipeline.nodes._html_builder import (
    build_answers_html,
    build_exam_html,
)
from app.modules.ExamForge_V1.test_runtime.frontend_report import (
    FrontendReportInput,
    build_frontend_report,
    json_text,
)
from app.modules.ExamForge_V1.test_runtime.gemini_cli_passthrough import (
    GeminiCliCapture,
    GeminiCliPassthrough,
)
from app.modules.ExamForge_V1.test_runtime.prompt_builder import (
    build_exam_json_prompt,
    sample_source_text,
)


def main() -> None:
    """CLI 진입점."""
    args = _parse_args()
    result = asyncio.run(_run(args))
    print(result)


async def _run(args: argparse.Namespace) -> str:
    """Gemini CLI 호출부터 보고서 저장까지 수행한다."""
    source_text = _source_text(args)
    prompt = build_exam_json_prompt(
        source_text=source_text,
        subject=args.subject,
        total_questions=args.total_questions,
        locale=args.locale,
        template_id=args.template_id,
    )
    connector = GeminiCliPassthrough(model=args.model)
    capture = await connector.capture(prompt, timeout_sec=args.timeout_sec)
    out_dir = _output_dir(args.output_dir)
    prefix = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    _write_json(out_dir / f"{prefix}_capture.json", capture.to_dict())
    _write_text(out_dir / f"{prefix}_raw_response.txt", capture.raw_response)
    parsed, parse_error = _parse_response(capture.raw_response)
    try:
        exam_html, answers_html = _render(parsed)
    except Exception as exc:  # pragma: no cover - exact renderer failure type is data-dependent.
        exam_html = ""
        answers_html = ""
        parse_error = _join_errors(
            parse_error,
            f"ExamForge HTML 렌더링 실패: {type(exc).__name__}: {exc}",
        )
    report = build_frontend_report(
        FrontendReportInput(
            capture=capture,
            parsed_json_text=json_text(parsed),
            exam_html=exam_html,
            answers_html=answers_html,
            parse_error=parse_error,
        )
    )
    report_path = out_dir / f"{prefix}_frontend_report.html"
    _write_text(report_path, report)
    return str(report_path)


def _join_errors(*messages: str | None) -> str | None:
    """보고서에 표시할 오류 메시지를 합친다."""
    cleaned = [message for message in messages if message]
    return " / ".join(cleaned) if cleaned else None


def _parse_args() -> argparse.Namespace:
    """명령행 인자를 파싱한다."""
    parser = argparse.ArgumentParser(description="ExamForge Gemini CLI live report")
    parser.add_argument("--subject", default="Rust")
    parser.add_argument("--source-file")
    parser.add_argument("--total-questions", type=int, default=5)
    parser.add_argument("--locale", default="ko")
    parser.add_argument("--template-id", default="ko_multiple_choice_5")
    parser.add_argument("--model", default=os.getenv("EXAMFORGE_GEMINI_CLI_MODEL"))
    parser.add_argument("--timeout-sec", type=int, default=None)
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args()


def _source_text(args: argparse.Namespace) -> str:
    """파일 입력이 있으면 읽고, 없으면 샘플 자료를 사용한다."""
    if args.source_file:
        return Path(args.source_file).read_text(encoding="utf-8")
    return sample_source_text()


def _parse_response(text: str) -> tuple[dict[str, object], str | None]:
    """Gemini 응답에서 JSON 객체를 읽는다. 실패하면 원문 보존용 오류만 반환한다."""
    try:
        value = _decode_json_object(text)
    except ValueError as exc:
        return {}, f"Gemini 응답 JSON 파싱 실패: {exc}"
    if not isinstance(value, dict):
        return {}, "Gemini 응답이 JSON 객체가 아닙니다."
    return value, None


def _decode_json_object(text: str) -> object:
    """텍스트 안의 첫 JSON 객체를 디코딩한다."""
    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        return value
    if last_error:
        raise ValueError(str(last_error)) from None
    raise ValueError("JSON 객체 시작 문자를 찾지 못했습니다.")


def _render(payload: dict[str, object]) -> tuple[str, str]:
    """파싱된 데이터를 변경하지 않고 ExamForge HTML 렌더러에 전달한다."""
    plan = payload.get("exam_plan")
    questions = payload.get("questions")
    if not isinstance(plan, dict) or not isinstance(questions, list):
        return "", ""
    question_dicts = [q for q in questions if isinstance(q, dict)]
    return build_exam_html(question_dicts, plan), build_answers_html(question_dicts, plan)


def _output_dir(raw: str | None) -> Path:
    """보고서 산출물 디렉터리를 만든다."""
    default = "app/modules/ExamForge_V1/artifacts/gemini_cli_reports"
    path = Path(raw or os.getenv("EXAMFORGE_GEMINI_CLI_REPORT_DIR", default))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, value: dict[str, object]) -> None:
    """JSON 산출물을 저장한다."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    """텍스트 산출물을 저장한다."""
    path.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    main()
