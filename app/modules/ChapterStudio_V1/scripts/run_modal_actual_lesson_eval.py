from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.modules.ChapterStudio_V1.ai_connectors.qwen27b_modal_connector import Qwen27BModalConnector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.app.frontend_payload import iframe_srcdoc
from app.modules.ChapterStudio_V1.postprocess.pipeline import PostprocessResult, SlideInput, postprocess_all
from app.modules.ChapterStudio_V1.scripts.run_modal_quality_eval import (
    DEFAULT_OCR_JSONL,
    _count_refs,
    _extract_ref_pages,
    _h,
    _reference_context,
    _reference_pages,
    _sentence_count,
)

REPORT_ROOT = ROOT / "artifacts" / "modal_actual_lesson"
B200_USD_PER_SEC = 0.001736
SCALEDOWN_WINDOW_SEC = 120
PASS_SCORE = 95
VOICE_TARGET_MIN_CHARS = 850
VOICE_TARGET_MAX_CHARS = 2400
VOICE_RETRY_LIMIT = 3
VOICE_FINAL_REWRITE_LIMIT = 1
VOICE_SEGMENT_COUNT = 4
_ACTION_RE = re.compile(r"(작성|비교|계산|분류|점검|설명|표시|풀|분석|구축|처리|해석|선택|서술|확인|탐색|평가|도출|적용)")
_WEAK_STOPWORDS = {
    "자주", "반대로", "이해함", "방지", "기법", "기법을", "문제", "상황", "상황에", "맞게", "고르지", "못함",
    "순서", "순서를", "문제풀이", "문제풀", "근거", "근거로", "연결", "연결하", "연결하는", "약함", "보고", "판단", "판단하", "판단하는", "습관",
}


class LessonSlide(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, le=14)
    title: str = Field(min_length=1, max_length=48)
    focus: str = Field(min_length=1, max_length=160)
    checkpoint: str = Field(min_length=1, max_length=200)
    category: str = Field(pattern="^(text|diagram|code|math|chart|interactive|table)$")
    html: str = Field(min_length=1, max_length=5600)
    css: str = Field(default="", max_length=1400)


class LessonQuiz(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, le=14)
    question: str = Field(min_length=1, max_length=180)
    choices: list[str] = Field(min_length=4, max_length=4)
    answer_idx: int = Field(ge=0, le=3)
    difficulty: str = Field(pattern="^(상|중|하|hard|medium|easy|기억|이해|적용|함정 교정|실전 판단|오해)$")
    explanation: str = Field(min_length=1, max_length=720)


class LessonNoteBlock(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    heading: str = Field(min_length=1, max_length=30)
    bullets: list[str] = Field(min_length=2, max_length=5)


class LessonAssignment(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    title: str = Field(min_length=1, max_length=60)
    assignment_format: str = Field(min_length=2, max_length=80)
    expected_minutes: int = Field(ge=5, le=90)
    steps: list[str] = Field(min_length=3, max_length=5)
    rubric: list[str] = Field(min_length=3, max_length=5)


class LessonVoiceScript(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, le=14)
    script_text: str = Field(min_length=1, max_length=2400)


class LessonVoiceSegment(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, le=14)
    segment_idx: int = Field(ge=0, le=3)
    segment_text: str = Field(min_length=1, max_length=900)


class LessonPayload(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slides: list[LessonSlide] = Field(min_length=10, max_length=15)
    quizzes: list[LessonQuiz] = Field(min_length=10, max_length=15)
    note_blocks: list[LessonNoteBlock] = Field(min_length=3, max_length=5)
    assignment: LessonAssignment
    voice_scripts: list[LessonVoiceScript] = Field(min_length=10, max_length=15)


class VoiceExpansionPayload(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    voice_scripts: list[LessonVoiceScript] = Field(min_length=10, max_length=15)


class SupportingRepairPayload(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    quizzes: list[LessonQuiz] = Field(min_length=10, max_length=15)
    assignment: LessonAssignment


async def main() -> None:
    args = _parse_args()
    started = time.perf_counter()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = REPORT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    reference_context = _reference_context(Path(args.ocr_jsonl))
    payload_override: LessonPayload | None = None

    if args.payload_json:
        payload_text = Path(args.payload_json).read_text(encoding="utf-8")
        payload_override = LessonPayload.model_validate_json(payload_text)
        _validate_payload_replay_args(args, payload_override)
        response = ChapterAIResponse(
            text=payload_text,
            model=_meta_model(Path(args.raw_meta) if args.raw_meta else None),
            input_tokens=0,
            output_tokens=0,
            finish_reason="payload_replay",
        )
    elif args.raw_response:
        response = _response_from_raw(Path(args.raw_response), Path(args.raw_meta) if args.raw_meta else None)
    else:
        request = ChapterAIRequest(
            system=_system_prompt(args.slide_count, voice_expansion_planned=args.expand_voice),
            user=_user_prompt(
                args.slide_count,
                learner_profile=args.learner_profile,
                weak_points=args.weak_points,
                reference_context_prompt=_reference_prompt(reference_context),
                voice_expansion_planned=args.expand_voice,
            ),
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            extra={"slide_count": args.slide_count, "seed": args.seed},
        )
        response = await Qwen27BModalConnector().generate(request)
    wall_sec = time.perf_counter() - started
    if args.raw_response and args.raw_meta:
        wall_sec = _raw_wall_sec(Path(args.raw_meta), wall_sec)

    if args.payload_json and args.raw_meta:
        meta = _meta_from_existing(Path(args.raw_meta), run_id, args.learner_profile, args.weak_points)
    else:
        meta = _response_meta(
            run_id,
            response,
            wall_sec,
            args.slide_count,
            learner_profile=args.learner_profile,
            weak_points=args.weak_points,
        )
    _write_text(out_dir / "raw_response.txt", response.text)

    parse_error = ""
    result: dict[str, Any] | None = None
    payload_dump: dict[str, Any] | None = None
    warnings: list[str] = []
    try:
        payload = payload_override or _parse_payload(response.text, args.slide_count)
        if args.expand_voice:
            payload = await _expand_voice_scripts(
                payload,
                out_dir=out_dir,
                meta=meta,
                learner_profile=args.learner_profile,
                weak_points=args.weak_points,
                reference_context_prompt=_reference_prompt(reference_context),
                target_slide_idx=args.voice_slide_idx if args.voice_slide_idx >= 0 else None,
                segmented_only=args.voice_segmented_only,
            )
        if args.repair_supporting:
            payload = await _repair_supporting_materials(
                payload,
                out_dir=out_dir,
                meta=meta,
                weak_points=args.weak_points,
                reference_context_prompt=_reference_prompt(reference_context),
            )
        payload_dump = payload.model_dump()
        processed = await postprocess_all(_slide_inputs(payload), max_concurrency=8)
        warnings = [warning for slide in processed for warning in slide["warnings"]]
        result = _result(
            payload,
            processed,
            reference_pages=_reference_pages(reference_context),
            learner_profile=args.learner_profile,
            weak_points=args.weak_points,
        )
        _write_json(out_dir / "payload.json", payload_dump)
        _write_json(out_dir / "lesson_result.json", result)
    except Exception as exc:  # noqa: BLE001
        parse_error = f"{type(exc).__name__}: {exc}"

    _write_json(out_dir / "response_meta.json", meta)
    scorecard = _score(payload_dump, result, parse_error, warnings, args.slide_count, meta, args.weak_points)
    _write_json(out_dir / "scorecard.json", scorecard)
    _write_text(out_dir / "quality_report.html", _report_html(run_id, meta, scorecard, result, response.text, parse_error, warnings))
    _write_text(out_dir / "practical_report.html", _practical_report_html(run_id, meta, scorecard, result, response.text, parse_error, warnings))
    print(out_dir / "quality_report.html")
    print(out_dir / "practical_report.html")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Modal Qwen 원본 모델 10~15장 실전 강의 품질·비용 평가")
    parser.add_argument("--slide-count", type=int, default=12, choices=range(10, 16))
    parser.add_argument("--max-tokens", type=int, default=32000)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--ocr-jsonl", default=str(DEFAULT_OCR_JSONL))
    parser.add_argument("--raw-response", default="")
    parser.add_argument("--raw-meta", default="")
    parser.add_argument("--payload-json", default="")
    parser.add_argument("--expand-voice", action="store_true")
    parser.add_argument("--voice-slide-idx", type=int, default=-1, help="음성대본 재호출을 특정 slide_idx 하나로 제한한다.")
    parser.add_argument("--allow-full-voice-expansion", action="store_true", help="기존 payload 재생성에서 10~15개 대본 전체 재확장을 명시 허용한다.")
    parser.add_argument("--voice-segmented-only", action="store_true", help="대상 음성대본을 기존 단일 생성 없이 문단별 생성·병합 경로로만 재작성한다.")
    parser.add_argument("--repair-supporting", action="store_true")
    parser.add_argument("--learner-profile", default="자격증 필기 준비생")
    parser.add_argument("--weak-points", default="혼동행렬, 과대적합 방지, 전처리·모델링·해석 순서 연결")
    return parser.parse_args()


def _validate_payload_replay_args(args: argparse.Namespace, payload: LessonPayload) -> None:
    slide_count = len(payload.slides)
    if args.slide_count != slide_count:
        raise ValueError(f"payload_json 재실행 slide-count 불일치: args={args.slide_count}, payload={slide_count}")
    if args.expand_voice and args.voice_slide_idx < 0 and not args.allow_full_voice_expansion:
        raise ValueError("payload_json 재실행에서 전체 음성 재확장을 하려면 --allow-full-voice-expansion을 명시하거나 --voice-slide-idx를 지정해야 한다.")
    if args.voice_segmented_only and not args.expand_voice:
        raise ValueError("--voice-segmented-only는 --expand-voice와 함께 써야 한다.")


def _system_prompt(slide_count: int, *, voice_expansion_planned: bool = False) -> str:
    voice_contract = (
        "voice_scripts[i] 키는 정확히 slide_idx, script_text 두 개이며, 문자열 배열로 쓰지 않는다. "
        "voice_scripts는 2차 TTS 대본 확장에서 다시 길게 생성할 초안이므로, script_text는 5~7문장으로 간결하게 쓰되 p.번호와 약점 핵심어를 포함한다. "
        if voice_expansion_planned
        else
        "voice_scripts[i] 키는 정확히 slide_idx, script_text 두 개이며, 문자열 배열로 쓰지 않는다. "
        "모든 voice_scripts[i].script_text는 8~12문장, 900~1600자 수준의 자세한 과외 대본이며, '여기서 헷갈리기 쉬운 지점은' 또는 '이 약점은' 문구와 취약점 핵심어를 포함한다. "
    )
    return (
        "너는 ChapterStudio_V1의 실전 강의 생성기다. 출력은 단일 JSON 객체 한 개뿐이다. "
        "JSON 외 텍스트, 사고과정, markdown fence, <think> 블록을 금지한다. "
        "최상위 키는 정확히 slides, quizzes, note_blocks, assignment, voice_scripts 다섯 개다. "
        f"slides, quizzes, voice_scripts는 각각 정확히 {slide_count}개다. "
        "slides[i] 키는 정확히 slide_idx, title, focus, checkpoint, category, html, css 일곱 개다. "
        "category 값은 text, diagram, code, math, chart, interactive, table 중 하나다. "
        "표가 주 시각자료인 슬라이드는 category를 table로 둔다. "
        "시각 슬롯은 반드시 지킨다: slide_idx 0은 mermaid diagram, 1은 chart-box chart, 2는 table, 3은 code, 4는 formula math, 5는 details interactive다. "
        "slide_idx 6~11은 category가 아니라 html 안에 각각 metric-card, flow-strip, comparison-table, timeline, step-grid, metric-card class를 반드시 넣는다. "
        "slide_idx 12는 category=diagram 및 flow-strip, slide_idx 13은 category=table 및 comparison-table, slide_idx 14는 category=interactive 및 step-grid를 쓴다. "
        "코드 블록은 slide_idx 3에서만 쓰고, 다른 슬라이드에는 <pre><code>를 넣지 않는다. "
        "category 값에 metric-card, flow-strip, comparison-table, timeline, step-grid를 쓰면 실패다. "
        "quizzes[i] 키는 정확히 slide_idx, question, choices, answer_idx, difficulty, explanation 여섯 개다. "
        "quizzes[i].slide_idx는 연결되는 slides[i].slide_idx와 같아야 한다. "
        "difficulty 값은 반드시 기억, 이해, 적용, 함정 교정, 실전 판단, 오해 중 하나만 쓴다. Easy/Medium/Hard 금지. "
        "choices는 문자열 4개 배열이고, answer_idx는 0~3 정수다. options, answer, correct 같은 대체 키를 쓰지 않는다. "
        "quiz explanation은 120~180자로, 정답 이유와 오답 함정을 함께 설명한다. "
        "모든 quiz explanation에는 '오답 함정:'과 '약점 연결:' 문자열을 둘 다 포함한다. "
        "note_blocks[i] 키는 정확히 heading, bullets 두 개다. title 키를 쓰지 않는다. "
        "note_blocks는 정확히 4개이며 각 block은 bullets 3개를 가진다. 각 bullet은 45자 이상이며, '약점 연결:' 문자열과 취약점 핵심어를 포함하고, 참고도서가 있으면 heading이 아니라 bullet 본문마다 p.번호를 넣는다. "
        f"{voice_contract}"
        "참고도서가 있으면 모든 voice_scripts[i].script_text에 p.7처럼 소문자 p와 마침표 형식의 페이지 번호를 1회 이상 넣는다. "
        "note_blocks는 3~5개이며, assignment는 title, assignment_format, expected_minutes, steps, rubric을 모두 포함한다. "
        "assignment steps와 rubric의 모든 항목에는 p.번호를 넣고, '약점 교정:' 또는 '평가 기준:' 표현과 취약점 핵심어를 포함한다. "
        "참고도서 발췌가 있으면 발췌 페이지 번호 안에서만 p.번호를 인용한다."
    )


def _user_prompt(
    slide_count: int,
    *,
    learner_profile: str,
    weak_points: str,
    reference_context_prompt: str,
    voice_expansion_planned: bool = False,
) -> str:
    core_terms = ", ".join(_prompt_weak_terms(weak_points))
    voice_contract = (
        "voice_scripts는 2차 TTS 대본 확장에서 다시 확장할 초안이다. 각 script_text는 5~7문장으로 간결하게 쓰고, 모든 문장을 자연스러운 존댓말로 작성하며, p.번호와 취약점 핵심어를 포함한다. "
        if voice_expansion_planned
        else
        "voice_scripts는 객체 배열이며 각 객체는 slide_idx와 script_text를 가진다. script_text는 슬라이드마다 8~12문장, 900~1600자 수준으로 쓰고, 모든 문장을 자연스러운 존댓말로 작성하며, TTS에 바로 넣을 수 있는 실제 과외식 말투로 작성하고 HTML 태그를 넣지 않는다. "
        "각 script_text는 화면에 없는 깊은 설명을 맡는다. 반드시 직관 설명, 실전 시험 판단법, 자주 틀리는 오답 함정, 사용자의 약점 교정, 참고도서 p.번호, 바로 해볼 미니연습을 자연스럽게 포함한다. "
    )
    return (
        "주제: 빅데이터 분석기사 필기 실전 연결 강의\n"
        f"학습자: {learner_profile}\n"
        "목표: 데이터 탐색, 모델링, 결과 해석을 문제풀이 판단 흐름으로 연결한다.\n"
        f"취약점: {weak_points}\n"
        f"취약점 핵심어 목록: {core_terms}\n"
        "금지: 종합 판단, 비즈니스 목표, 문제 풀이, 검증 기법처럼 취약점 핵심어 목록에 없는 표현만으로 약점 연결을 대체하면 실패다.\n"
        f"{reference_context_prompt}\n"
        f"실전 1강으로 {slide_count}장의 HTML 슬라이드를 만든다. slide_idx는 0부터 {slide_count - 1}까지 정확히 한 번씩 쓴다. "
        "이 강의는 반드시 사용자 맞춤형 1강이다. 전체 커리큘럼을 한 번에 만들지 말고, 이 학습자의 취약점 교정에 맞춘 한 강의만 만든다. "
        "각 slide.focus 또는 slide.checkpoint에는 '약점 교정:' 문구와 취약점 핵심어 목록 중 하나를 정확히 포함한다. "
        "각 slide 객체는 반드시 title/focus/checkpoint/category/html/css를 모두 채운다. "
        "category는 text, diagram, code, math, chart, interactive, table 중 하나다. "
        "필수 시각 슬롯: slide_idx 0 category=diagram 및 <pre class=\"mermaid\">, slide_idx 1 category=chart 및 chart-box, slide_idx 2 category=table 및 comparison-table, slide_idx 3 category=code 및 <pre><code data-lang=\"python\">, slide_idx 4 category=math 및 <div class=\"formula\">, slide_idx 5 category=interactive 및 <details>를 반드시 넣는다. "
        "slide_idx 6 category=text 및 HTML에는 metric-card, 7 category=diagram 및 HTML에는 flow-strip, 8 category=table 및 HTML에는 comparison-table, 9 category=diagram 및 HTML에는 timeline, 10 category=interactive 및 HTML에는 step-grid, 11 category=text 및 HTML에는 metric-card를 넣는다. "
        "slide_idx 12 category=diagram 및 HTML에는 flow-strip, 13 category=table 및 HTML에는 comparison-table, 14 category=interactive 및 HTML에는 step-grid를 넣는다. "
        "코드 블록은 slide_idx 3에만 넣고, slide_idx 13이나 다른 슬라이드에는 <pre><code>를 넣지 않는다. "
        "한 슬라이드는 한 화면 학습 단위이며, h2, 핵심 설명, 시각 단서, 짧은 예시, 오해/주의, 자가점검을 포함한다. "
        "각 slide.html에는 취약점 핵심어 목록 중 하나와 연결되는 '오답 함정' 또는 '헷갈리는 지점' 문장을 반드시 1개 이상 넣는다. "
        "각 slide.html 본문에는 마침표로 끝나는 완전한 한국어 문장 4~7개를 넣고, 핵심어만 나열한 조각문장으로 끝내지 않는다. "
        "슬라이드는 가벼운 시각자료 중심이어야 하므로 본문 설명은 한국어 200~360자 안에서 끝내고, 긴 설명은 voice_scripts로 보낸다. "
        "각 slide.html은 section 본문만 쓰고 script, 외부 URL, markdown fence를 넣지 않는다. "
        "기본 화면은 라이트모드이며 배경은 #F8F8F6, #FFFDF7, #F3F7FB 같은 부드러운 학습색을 쓴다. "
        "어두운 배경 박스에는 #FFFFFF 또는 #F8F8F6 수준의 밝은 글자를 쓰고, 연한 회색 글자나 투명도 낮은 글자를 쓰지 않는다. "
        "모든 슬라이드에는 metric-card, flow-strip, comparison-table, timeline, step-grid, table, figure, chart-box, mermaid, code-card, formula, details 중 하나 이상을 넣는다. "
        "전체 강의에는 chart-box data-chart-spec 차트, <pre class=\"mermaid\">flowchart LR...</pre> 관계도, <pre><code data-lang=\"python\"> 코드, formula, details 실습이 최소 1회씩 포함되어야 한다. "
        "text형 슬라이드도 긴 문단만 두지 말고 metric-card, flow-strip, comparison-table, node-link-visual 중 하나로 핵심을 시각화한다. "
        "interactive 슬라이드는 button만 나열하면 실패다. 반드시 <details open><summary>...</summary>...</details>를 포함하고, 단계형이면 step-grid, 노드 연결형이면 node-link-visual, 연결리스트형이면 linked-list, 그래프형이면 graph-map을 함께 쓴다. "
        "연결리스트 예시는 <ol class=\"linked-list\"><li>head</li><li>node</li><li>null</li></ol> 형식으로 쓰고, 그래프 예시는 <div class=\"graph-map\"><div class=\"graph-node\">A</div><div class=\"graph-node\">B</div></div> 또는 <svg class=\"node-link-visual\" viewBox=\"0 0 600 220\"><line x1=\"120\" y1=\"110\" x2=\"300\" y2=\"110\"/><circle cx=\"120\" cy=\"110\" r=\"42\"/><text x=\"120\" y=\"116\" text-anchor=\"middle\">A</text><circle cx=\"300\" cy=\"110\" r=\"42\"/><text x=\"300\" y=\"116\" text-anchor=\"middle\">B</text></svg> 형식으로 쓴다. "
        "코드 슬라이드는 from, def, 변수, 출력 해석을 포함하고, 코드 아래에 줄별 해석 리스트를 붙인다. "
        "차트는 <div class=\"chart-box\" data-chart-type=\"bar\" data-chart-spec='{\"data\":{\"labels\":[\"탐색\",\"모델링\",\"해석\"],\"values\":[30,40,30]},\"title\":\"실전 판단 비중\",\"colors\":[\"#2A3B45\",\"#207B4C\",\"#7A6518\"]}'></div> 형식을 쓴다. "
        "모든 chart-box의 data-chart-spec.data.values는 반드시 [30,40,30]처럼 1차원 숫자 배열이어야 하며, [[1,2],[3,4]] 같은 중첩 배열, 히트맵, 행렬 차트는 쓰지 않는다. "
        "각 슬라이드 css는 슬라이드 고유 레이아웃만 900자 이하로 쓴다. "
        f"quizzes는 정확히 {slide_count}개이며 각 quiz는 slide_idx, question, choices 4개, answer_idx 정수, difficulty, explanation을 모두 가진다. "
        f"각 quiz.slide_idx는 0부터 {slide_count - 1}까지 정확히 한 번씩 쓰고, 같은 번호 슬라이드의 핵심 내용을 평가한다. "
        "difficulty는 Easy/Medium/Hard가 아니라 기억/이해/적용/함정 교정/실전 판단/오해 중 하나로 쓴다. "
        f"quiz explanation은 120~180자로 쓰고, 왜 정답인지와 왜 헷갈리는 보기가 틀렸는지를 함께 적는다. 모든 explanation에는 '오답 함정:'과 '약점 연결:' 표현을 둘 다 넣고, 취약점 핵심어 목록({core_terms}) 중 최소 1개를 정확히 쓴다. "
        f"{voice_contract}"
        f"각 script_text에는 '여기서 헷갈리기 쉬운 지점은' 또는 '이 약점은'으로 시작하는 취약점 교정 문장을 정확히 1문장 이상 넣고, 그 문장 안에 취약점 핵심어 목록({core_terms}) 중 최소 1개를 정확히 쓴다. "
        "참고도서가 있으면 각 script_text마다 'p.7을 다시 보면', 'p.8의 표를 확인하면'처럼 p.번호를 반드시 1회 이상 말한다. "
        "note_blocks는 암기카드가 아니라 핵심정리 블록이며 정확히 4개를 만든다. 각 블록은 heading과 정확히 3개 bullets를 가진다. "
        f"note_blocks의 p.번호는 heading에 넣지 말고 모든 bullet 문장마다 넣는다. 각 bullet은 45자 이상으로 쓰고 '약점 연결:' 표현, 취약점 핵심어 목록({core_terms}) 중 최소 1개, 개념, 실전 판단, 오해 방지를 한 문장에 담는다. "
        "assignment.assignment_format은 제출 형식(예: 문제풀이+근거 표시)을 명확히 쓰고, expected_minutes는 20~40 사이 정수로 쓴다. "
        f"assignment steps와 rubric은 해당 강의의 핵심내용을 바탕으로 해야 하며, 각 항목에 p.번호, '약점 교정:' 또는 '평가 기준:' 표현, 취약점 핵심어 목록({core_terms}) 중 최소 1개를 모두 포함한다. "
        "참고도서가 제공된 경우 note_blocks의 모든 bullet, voice_scripts의 모든 script_text, assignment steps와 rubric의 모든 항목에 p.번호를 넣는다."
    )


def _reference_prompt(context: Any) -> str:
    if context is None or not context.has_hits():
        return ""
    lines = ["참고도서 발췌(OCR 기반, 이 페이지 안에서만 p.번호 인용):"]
    for hit in context.hits[:5]:
        lines.append(f"- p.{hit.page}: {hit.snippet[:420]}")
    return "\n".join(lines)


def _parse_payload(text: str, slide_count: int) -> LessonPayload:
    raw = _extract_json_object(text)
    try:
        payload = LessonPayload.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError(f"실전 강의 JSON 검증 실패: {exc}") from exc
    expected = set(range(slide_count))
    slide_idx = {slide.slide_idx for slide in payload.slides}
    quiz_idx = {quiz.slide_idx for quiz in payload.quizzes}
    quiz_ok = quiz_idx == expected
    voice_idx = {script.slide_idx for script in payload.voice_scripts}
    if slide_idx != expected or voice_idx != expected or not quiz_ok:
        raise ValueError(f"슬라이드/퀴즈/대본 개수 계약 불일치: slides={slide_idx}, voices={voice_idx}, quizzes={quiz_idx}")
    return payload


async def _expand_voice_scripts(
    payload: LessonPayload,
    *,
    out_dir: Path,
    meta: dict[str, Any],
    learner_profile: str,
    weak_points: str,
    reference_context_prompt: str,
    target_slide_idx: int | None = None,
    segmented_only: bool = False,
) -> LessonPayload:
    started = time.perf_counter()
    connector = Qwen27BModalConnector()
    original_scripts = {script.slide_idx: script for script in payload.voice_scripts}
    accepted: dict[int, LessonVoiceScript] = dict(original_scripts)
    raw_records: list[dict[str, Any]] = []
    responses: list[ChapterAIResponse] = []
    target_slides = [
        slide for slide in payload.slides
        if target_slide_idx is None or slide.slide_idx == target_slide_idx
    ]
    if not target_slides:
        raise ValueError(f"voice-slide-idx가 강의 범위를 벗어났다: {target_slide_idx}")

    retry_targets: list[tuple[LessonSlide, str]] = []
    if segmented_only:
        retry_targets = [
            (slide, _voice_script_quality_note(accepted[slide.slide_idx].script_text))
            for slide in target_slides
        ]
    else:
        requests = [
            _voice_expansion_request(
                payload,
                slide,
                original_scripts[slide.slide_idx],
                learner_profile=learner_profile,
                weak_points=weak_points,
                reference_context_prompt=reference_context_prompt,
                retry_reason="",
                seed=200 + slide.slide_idx,
            )
            for slide in target_slides
        ]
        first_responses = await connector.generate_batch(requests)
        responses.extend(first_responses)
        for slide, response in zip(target_slides, first_responses, strict=True):
            script, reason = _voice_response_to_script(response.text, slide.slide_idx)
            raw_records.append(_voice_raw_record("initial", slide.slide_idx, response, reason))
            if script is not None and not _voice_script_needs_retry(script.script_text):
                accepted[slide.slide_idx] = script
            else:
                fallback = script or original_scripts[slide.slide_idx]
                accepted[slide.slide_idx] = fallback
                retry_targets.append((slide, reason or _voice_script_quality_note(fallback.script_text)))

        for retry_round in range(VOICE_RETRY_LIMIT):
            if not retry_targets:
                break
            retry_requests = [
                _voice_continuation_request(
                    payload,
                    slide,
                    accepted[slide.slide_idx],
                    learner_profile=learner_profile,
                    weak_points=weak_points,
                    reference_context_prompt=reference_context_prompt,
                    retry_reason=reason,
                    seed=500 + (retry_round * 100) + slide.slide_idx,
                )
                for slide, reason in retry_targets
            ]
            retry_responses = await connector.generate_batch(retry_requests)
            responses.extend(retry_responses)
            next_retry_targets = []
            for (slide, previous_reason), response in zip(retry_targets, retry_responses, strict=True):
                script, reason = _voice_response_to_script(response.text, slide.slide_idx)
                raw_records.append(_voice_raw_record(f"retry_{retry_round + 1}", slide.slide_idx, response, reason or previous_reason))
                if script is not None:
                    combined = LessonVoiceScript(
                        slide_idx=slide.slide_idx,
                        script_text=_combine_voice_text(accepted[slide.slide_idx].script_text, script.script_text),
                    )
                    if not _voice_script_needs_retry(combined.script_text):
                        accepted[slide.slide_idx] = combined
                    elif len(combined.script_text) > len(accepted[slide.slide_idx].script_text):
                        accepted[slide.slide_idx] = combined
                        next_retry_targets.append((slide, _voice_script_quality_note(combined.script_text)))
                    else:
                        next_retry_targets.append((slide, _voice_script_quality_note(accepted[slide.slide_idx].script_text)))
                else:
                    next_retry_targets.append((slide, reason or previous_reason))
            retry_targets = next_retry_targets

        for rewrite_round in range(VOICE_FINAL_REWRITE_LIMIT):
            if not retry_targets:
                break
            rewrite_requests = [
                _voice_full_rewrite_request(
                    payload,
                    slide,
                    accepted[slide.slide_idx],
                    learner_profile=learner_profile,
                    weak_points=weak_points,
                    reference_context_prompt=reference_context_prompt,
                    retry_reason=reason,
                    seed=900 + (rewrite_round * 100) + slide.slide_idx,
                )
                for slide, reason in retry_targets
            ]
            rewrite_responses = await connector.generate_batch(rewrite_requests)
            responses.extend(rewrite_responses)
            next_retry_targets = []
            for (slide, previous_reason), response in zip(retry_targets, rewrite_responses, strict=True):
                script, reason = _voice_response_to_script(response.text, slide.slide_idx)
                raw_records.append(_voice_raw_record(f"final_rewrite_{rewrite_round + 1}", slide.slide_idx, response, reason or previous_reason))
                if script is not None and not _voice_script_needs_retry(script.script_text):
                    accepted[slide.slide_idx] = script
                elif script is not None and _voice_quality_score(script.script_text) > _voice_quality_score(accepted[slide.slide_idx].script_text):
                    accepted[slide.slide_idx] = script
                    next_retry_targets.append((slide, _voice_script_quality_note(script.script_text)))
                else:
                    next_retry_targets.append((slide, reason or previous_reason))
            retry_targets = next_retry_targets

    if retry_targets:
        retry_targets = await _rewrite_voice_targets_by_segments(
            payload,
            retry_targets,
            accepted=accepted,
            connector=connector,
            raw_records=raw_records,
            responses=responses,
            learner_profile=learner_profile,
            weak_points=weak_points,
            reference_context_prompt=reference_context_prompt,
        )

    wall_sec = time.perf_counter() - started
    expanded_scripts = [accepted[slide.slide_idx] for slide in payload.slides]
    _write_json(out_dir / "raw_voice_expansion_responses.json", raw_records)
    _write_text(out_dir / "raw_voice_expansion_response.txt", "\n\n---\n\n".join(item["text"] for item in raw_records))
    _apply_voice_expansion_meta(meta, responses, wall_sec, retry_targets)
    return payload.model_copy(update={"voice_scripts": expanded_scripts})


def _voice_expansion_request(
    payload: LessonPayload,
    slide: LessonSlide,
    current_script: LessonVoiceScript,
    *,
    learner_profile: str,
    weak_points: str,
    reference_context_prompt: str,
    retry_reason: str,
    seed: int,
) -> ChapterAIRequest:
    return ChapterAIRequest(
        system=_voice_expansion_system(),
        user=_voice_expansion_user(
            payload,
            slide,
            current_script,
            learner_profile=learner_profile,
            weak_points=weak_points,
            reference_context_prompt=reference_context_prompt,
            retry_reason=retry_reason,
        ),
        max_tokens=2600,
        temperature=0,
        extra={"slide_count": 15, "schema": "voice_script", "voice_expansion": True, "seed": seed},
    )


def _voice_continuation_request(
    payload: LessonPayload,
    slide: LessonSlide,
    current_script: LessonVoiceScript,
    *,
    learner_profile: str,
    weak_points: str,
    reference_context_prompt: str,
    retry_reason: str,
    seed: int,
) -> ChapterAIRequest:
    return ChapterAIRequest(
        system=_voice_expansion_system(),
        user=_voice_continuation_user(
            payload,
            slide,
            current_script,
            learner_profile=learner_profile,
            weak_points=weak_points,
            reference_context_prompt=reference_context_prompt,
            retry_reason=retry_reason,
        ),
        max_tokens=2200,
        temperature=0,
        extra={"slide_count": 15, "schema": "voice_script", "voice_continuation": True, "seed": seed},
    )


def _voice_full_rewrite_request(
    payload: LessonPayload,
    slide: LessonSlide,
    current_script: LessonVoiceScript,
    *,
    learner_profile: str,
    weak_points: str,
    reference_context_prompt: str,
    retry_reason: str,
    seed: int,
) -> ChapterAIRequest:
    return ChapterAIRequest(
        system=_voice_expansion_system(),
        user=_voice_full_rewrite_user(
            payload,
            slide,
            current_script,
            learner_profile=learner_profile,
            weak_points=weak_points,
            reference_context_prompt=reference_context_prompt,
            retry_reason=retry_reason,
        ),
        max_tokens=3200,
        temperature=0.2,
        extra={"slide_count": 15, "schema": "voice_script", "voice_full_rewrite": True, "seed": seed},
    )


async def _rewrite_voice_targets_by_segments(
    payload: LessonPayload,
    retry_targets: list[tuple[LessonSlide, str]],
    *,
    accepted: dict[int, LessonVoiceScript],
    connector: Qwen27BModalConnector,
    raw_records: list[dict[str, Any]],
    responses: list[ChapterAIResponse],
    learner_profile: str,
    weak_points: str,
    reference_context_prompt: str,
) -> list[tuple[LessonSlide, str]]:
    segment_requests: list[ChapterAIRequest] = []
    segment_meta: list[tuple[LessonSlide, int, str]] = []
    for slide, reason in retry_targets:
        for segment_idx in range(VOICE_SEGMENT_COUNT):
            segment_requests.append(
                _voice_segment_request(
                    payload,
                    slide,
                    segment_idx,
                    learner_profile=learner_profile,
                    weak_points=weak_points,
                    reference_context_prompt=reference_context_prompt,
                    retry_reason=reason,
                    seed=1200 + slide.slide_idx * 10 + segment_idx,
                )
            )
            segment_meta.append((slide, segment_idx, reason))

    segment_responses = await connector.generate_batch(segment_requests)
    responses.extend(segment_responses)
    segments_by_slide: dict[int, dict[int, LessonVoiceSegment]] = {
        slide.slide_idx: {} for slide, _ in retry_targets
    }
    reasons_by_slide: dict[int, str] = {}
    for (slide, segment_idx, previous_reason), response in zip(segment_meta, segment_responses, strict=True):
        segment, reason = _voice_response_to_segment(response.text, slide.slide_idx, segment_idx)
        raw_records.append(_voice_raw_record(f"segment_{segment_idx}", slide.slide_idx, response, reason or previous_reason))
        if segment is not None:
            segments_by_slide[slide.slide_idx][segment_idx] = segment
        else:
            reasons_by_slide[slide.slide_idx] = reason or previous_reason

    remaining: list[tuple[LessonSlide, str]] = []
    for slide, previous_reason in retry_targets:
        segments = segments_by_slide[slide.slide_idx]
        if set(segments) != set(range(VOICE_SEGMENT_COUNT)):
            remaining.append((slide, reasons_by_slide.get(slide.slide_idx, previous_reason)))
            continue
        merged = LessonVoiceScript(
            slide_idx=slide.slide_idx,
            script_text=_merge_voice_segments([segments[idx].segment_text for idx in range(VOICE_SEGMENT_COUNT)]),
        )
        if not _voice_script_needs_retry(merged.script_text):
            accepted[slide.slide_idx] = merged
        elif _voice_quality_score(merged.script_text) > _voice_quality_score(accepted[slide.slide_idx].script_text):
            accepted[slide.slide_idx] = merged
            remaining.append((slide, _voice_script_quality_note(merged.script_text)))
        else:
            remaining.append((slide, previous_reason))
    return remaining


def _voice_segment_request(
    payload: LessonPayload,
    slide: LessonSlide,
    segment_idx: int,
    *,
    learner_profile: str,
    weak_points: str,
    reference_context_prompt: str,
    retry_reason: str,
    seed: int,
) -> ChapterAIRequest:
    return ChapterAIRequest(
        system=_voice_segment_system(),
        user=_voice_segment_user(
            payload,
            slide,
            segment_idx,
            learner_profile=learner_profile,
            weak_points=weak_points,
            reference_context_prompt=reference_context_prompt,
            retry_reason=retry_reason,
        ),
        max_tokens=1200,
        temperature=0.2,
        extra={"slide_count": len(payload.slides), "schema": "voice_segment", "voice_segment": True, "seed": seed},
    )


def _voice_expansion_system() -> str:
    return (
        "너는 ChapterStudio_V1의 TTS용 1:1 과외 음성대본 확장기다. 출력은 단일 JSON 객체 한 개뿐이다. "
        "JSON 외 텍스트, 사고과정, markdown fence, <think> 블록을 금지한다. "
        "최상위 키는 정확히 slide_idx, script_text 두 개뿐이다. "
        f"script_text는 {VOICE_TARGET_MIN_CHARS}~{VOICE_TARGET_MAX_CHARS}자, 12~28문장이다. "
        "HTML 태그, SSML, 목록 기호, 마크다운, 괄호 지시문, 따옴표 밖 줄바꿈을 금지한다. "
        "대본은 TTS가 바로 읽을 문단이므로 '요.', '다.', '죠.'를 섞은 자연스러운 존댓말을 사용하고 반말을 금지한다. "
        "긴 문장을 몰아쓰지 말고 쉼표와 짧은 문장으로 호흡을 만든다. "
        "영문 약어는 처음 나올 때 한국어 발음과 뜻을 같이 말한다. 예: FP, 에프 피, 거짓 양성. FN, 에프 엔, 거짓 음성. F1 Score, 에프 원 스코어. ROC-AUC, 알오씨 에이유씨. "
        "화면 문장 반복은 실패이며, 직관 설명, 실전 판단법, 오답 함정, 약점 교정, 참고도서 p.번호, 미니연습, 마무리 회상을 모두 자연스럽게 포함한다."
    )


def _voice_segment_system() -> str:
    return (
        "너는 ChapterStudio_V1의 TTS 대본 문단 작성기다. 출력은 단일 JSON 객체 한 개뿐이다. "
        "최상위 키는 정확히 slide_idx, segment_idx, segment_text 세 개다. "
        "JSON 외 텍스트, 사고과정, markdown fence, <think> 블록을 금지한다. "
        "segment_text는 230~520자, 자연스러운 존댓말 문단이다. "
        "HTML, SSML, 목록, 번호 목록, markdown, 괄호 지시문을 금지한다. "
        "TTS가 바로 읽을 문장으로 쓰고, '요.', '다.', '죠.'를 섞는다."
    )


def _voice_expansion_user(
    payload: LessonPayload,
    slide: LessonSlide,
    current_script: LessonVoiceScript,
    *,
    learner_profile: str,
    weak_points: str,
    reference_context_prompt: str,
    retry_reason: str,
) -> str:
    previous_title = payload.slides[slide.slide_idx - 1].title if slide.slide_idx > 0 else "없음"
    next_title = payload.slides[slide.slide_idx + 1].title if slide.slide_idx + 1 < len(payload.slides) else "없음"
    slide_text = _plain_text(slide.html)[:900]
    retry_line = f"이전 시도 미달 사유: {retry_reason}\n" if retry_reason else ""
    return (
        f"학습자: {learner_profile}\n"
        f"취약점: {weak_points}\n"
        f"{reference_context_prompt}\n"
        f"{retry_line}"
        f"전체 강의 위치: {len(payload.slides)}장 중 {slide.slide_idx + 1}장\n"
        f"이전 슬라이드: {previous_title}\n"
        f"다음 슬라이드: {next_title}\n"
        f"이번 슬라이드 제목: {slide.title}\n"
        f"이번 슬라이드 초점: {slide.focus}\n"
        f"이번 슬라이드 자가점검: {slide.checkpoint}\n"
        f"이번 슬라이드 화면 텍스트 요약: {slide_text}\n"
        f"초안 대본: {current_script.script_text[:900]}\n"
        "해야 할 일: 위 한 장에 대해서만 slide_idx와 script_text를 생성한다.\n"
        f"slide_idx는 반드시 {slide.slide_idx}다.\n"
        "script_text 작성 순서: 짧은 도입, 직관 설명, 참고도서 p.번호 연결, 실전 시험 판단법, 오답 함정, 사용자 약점 교정, 20초 미니연습, 마무리 회상 순서로 한 문단처럼 자연스럽게 이어 말한다.\n"
        "말투: 실제 과외 선생님처럼 차분하고 구체적인 존댓말로 말한다. '자,', '여기서', '한 번 멈춰서 생각해봅시다', '실전에서는', '오답 함정은', '이 약점은', '마지막으로' 중 5개 이상을 자연스럽게 넣는다.\n"
        "발음: FP나 FN 같은 약어가 나오면 'FP, 에프 피, 거짓 양성'처럼 읽을 발음을 붙인다. 슬래시로 FP/FN처럼 쓰지 말고 '에프 피와 에프 엔'처럼 읽히게 쓴다.\n"
        "TTS 금지: <speak>, SSML, [pause], (천천히), 글머리표, 번호 목록, HTML, markdown을 넣지 않는다.\n"
        f"길이: {VOICE_TARGET_MIN_CHARS}자 미만이면 실패, {VOICE_TARGET_MAX_CHARS}자 초과도 실패다."
    )


def _voice_segment_user(
    payload: LessonPayload,
    slide: LessonSlide,
    segment_idx: int,
    *,
    learner_profile: str,
    weak_points: str,
    reference_context_prompt: str,
    retry_reason: str,
) -> str:
    previous_title = payload.slides[slide.slide_idx - 1].title if slide.slide_idx > 0 else "없음"
    next_title = payload.slides[slide.slide_idx + 1].title if slide.slide_idx + 1 < len(payload.slides) else "없음"
    slide_text = _plain_text(slide.html)[:900]
    segment_goals = [
        "도입과 화면 해석. '자,'와 '여기서'를 넣고, 슬라이드의 핵심을 말로 풀어 설명한다.",
        "공식과 직관. 참고도서 p.번호를 연결하고, 분자와 분모 또는 판단 기준을 실제 상황으로 바꿔 설명한다.",
        "실전 판단과 오답 함정. '실전에서는', '오답 함정은', '이 약점은'을 모두 넣고, FP, FN이 나오면 에프 피, 에프 엔 발음을 함께 쓴다.",
        "20초 미니연습과 마무리. '한 번 멈춰서 생각해봅시다'와 '마지막으로'를 넣고, 다음 슬라이드와 자연스럽게 연결한다.",
    ]
    return (
        f"학습자: {learner_profile}\n"
        f"취약점: {weak_points}\n"
        f"{reference_context_prompt}\n"
        f"이전 전체 대본 미달 사유: {retry_reason}\n"
        f"전체 강의 위치: {len(payload.slides)}장 중 {slide.slide_idx + 1}장\n"
        f"이전 슬라이드: {previous_title}\n"
        f"다음 슬라이드: {next_title}\n"
        f"이번 슬라이드 제목: {slide.title}\n"
        f"이번 슬라이드 초점: {slide.focus}\n"
        f"이번 슬라이드 자가점검: {slide.checkpoint}\n"
        f"이번 슬라이드 화면 텍스트 요약: {slide_text}\n"
        f"해야 할 일: slide_idx={slide.slide_idx}, segment_idx={segment_idx}인 문단 하나만 작성한다.\n"
        f"문단 목표: {segment_goals[segment_idx]}\n"
        "각 문단은 230~520자이며, 앞뒤 문단을 몰라도 자연스럽게 이어질 수 있게 쓴다.\n"
        "이미 실패한 짧은 대본을 반복하지 말고, 문단 목표에 해당하는 새 설명만 작성한다.\n"
        "TTS 금지: <speak>, SSML, [pause], 괄호 지시문, 글머리표, 번호 목록, HTML, markdown을 넣지 않는다."
    )


def _voice_continuation_user(
    payload: LessonPayload,
    slide: LessonSlide,
    current_script: LessonVoiceScript,
    *,
    learner_profile: str,
    weak_points: str,
    reference_context_prompt: str,
    retry_reason: str,
) -> str:
    previous_title = payload.slides[slide.slide_idx - 1].title if slide.slide_idx > 0 else "없음"
    next_title = payload.slides[slide.slide_idx + 1].title if slide.slide_idx + 1 < len(payload.slides) else "없음"
    return (
        f"학습자: {learner_profile}\n"
        f"취약점: {weak_points}\n"
        f"{reference_context_prompt}\n"
        f"이전 시도 미달 사유: {retry_reason}\n"
        f"이번 슬라이드 제목: {slide.title}\n"
        f"이번 슬라이드 초점: {slide.focus}\n"
        f"이전 슬라이드: {previous_title}\n"
        f"다음 슬라이드: {next_title}\n"
        f"현재 대본 글자 수: {len(current_script.script_text)}\n"
        f"현재 대본: {current_script.script_text}\n"
        "해야 할 일: 현재 대본 전체를 다시 쓰지 말고, 바로 뒤에 붙일 추가 설명만 script_text에 작성한다.\n"
        f"slide_idx는 반드시 {slide.slide_idx}다.\n"
        "추가 설명은 650~950자이며, 현재 대본과 같은 문장을 반복하지 않는다.\n"
        "추가 설명에는 반드시 직관 설명, 실전 판단법, 오답 함정, 사용자의 약점 교정, 참고도서 p.번호, 20초 미니연습, 다음 슬라이드 연결 문장을 포함한다.\n"
        "말투는 자연스러운 존댓말이며 '자,', '여기서', '실전에서는', '오답 함정은', '이 약점은', '마지막으로' 중 4개 이상을 넣는다.\n"
        "FP, FN, F1 Score, ROC-AUC 같은 약어가 나오면 반드시 에프 피, 에프 엔, 에프 원 스코어, 알오씨 에이유씨처럼 읽을 발음을 같이 쓴다.\n"
        "TTS 금지: <speak>, SSML, [pause], 괄호 지시문, 글머리표, 번호 목록, HTML, markdown을 넣지 않는다."
    )


def _voice_full_rewrite_user(
    payload: LessonPayload,
    slide: LessonSlide,
    current_script: LessonVoiceScript,
    *,
    learner_profile: str,
    weak_points: str,
    reference_context_prompt: str,
    retry_reason: str,
) -> str:
    previous_title = payload.slides[slide.slide_idx - 1].title if slide.slide_idx > 0 else "없음"
    next_title = payload.slides[slide.slide_idx + 1].title if slide.slide_idx + 1 < len(payload.slides) else "없음"
    slide_text = _plain_text(slide.html)[:1000]
    return (
        f"학습자: {learner_profile}\n"
        f"취약점: {weak_points}\n"
        f"{reference_context_prompt}\n"
        f"이전 시도 미달 사유: {retry_reason}\n"
        f"전체 강의 위치: {len(payload.slides)}장 중 {slide.slide_idx + 1}장\n"
        f"이전 슬라이드: {previous_title}\n"
        f"다음 슬라이드: {next_title}\n"
        f"이번 슬라이드 제목: {slide.title}\n"
        f"이번 슬라이드 초점: {slide.focus}\n"
        f"이번 슬라이드 자가점검: {slide.checkpoint}\n"
        f"이번 슬라이드 화면 텍스트 요약: {slide_text}\n"
        f"이전 대본 글자 수: {len(current_script.script_text)}\n"
        "해야 할 일: 이전 대본을 이어 쓰지 말고, 이번 슬라이드의 TTS용 전체 대본을 새로 작성한다.\n"
        f"slide_idx는 반드시 {slide.slide_idx}다.\n"
        f"script_text는 {VOICE_TARGET_MIN_CHARS}~1400자, 18~26문장으로 작성한다. 850자 미만이면 실패다.\n"
        "각 문장은 너무 짧게 끊지 말고, 핵심 문장은 35자 이상으로 풀어 쓴다.\n"
        "필수 흐름: 자, 로 시작해 화면을 짚고, 직관 설명을 풀고, 공식의 분자와 분모를 말로 바꾸고, 참고도서 p.번호를 연결하고, 실전에서는 어떻게 판단하는지 말하고, 오답 함정은 무엇인지 짚고, 이 약점은 어떻게 고치는지 말하고, 20초 미니연습을 내고, 마지막으로 다음 슬라이드와 연결한다.\n"
        "추가 필수 내용: 정확도가 높은데도 틀린 모델의 예시, 클래스 불균형 상황, 정밀도와 재현율을 같이 보는 이유, 문제에서 비용 조건을 찾는 방법을 각각 다른 문장으로 설명한다.\n"
        "필수 단어: 실전, 오답 함정, 이 약점, 판단, 연습, p.번호 표현을 모두 포함한다.\n"
        "말투: 실제 과외 선생님처럼 차분한 존댓말로 말한다. '자,', '여기서', '한 번 멈춰서 생각해봅시다', '실전에서는', '오답 함정은', '이 약점은', '마지막으로'를 모두 자연스럽게 넣는다.\n"
        "발음: FP, FN, F1 Score, ROC-AUC 같은 약어가 나오면 '에프 피', '에프 엔', '에프 원 스코어', '알오씨 에이유씨'처럼 읽을 발음을 반드시 함께 쓴다.\n"
        "TTS 금지: <speak>, SSML, [pause], 괄호 지시문, 글머리표, 번호 목록, HTML, markdown을 넣지 않는다."
    )


def _parse_voice_expansion(text: str, slide_count: int) -> VoiceExpansionPayload:
    raw = _extract_json_object(text)
    try:
        payload = VoiceExpansionPayload.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError(f"음성대본 확장 JSON 검증 실패: {exc}") from exc
    expected = set(range(slide_count))
    voice_idx = {script.slide_idx for script in payload.voice_scripts}
    if voice_idx != expected:
        raise ValueError(f"음성대본 확장 slide_idx 불일치: {voice_idx}")
    return payload


def _voice_response_to_script(text: str, expected_idx: int) -> tuple[LessonVoiceScript | None, str]:
    try:
        return _parse_single_voice_script(text, expected_idx), ""
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _parse_single_voice_script(text: str, expected_idx: int) -> LessonVoiceScript:
    raw = _extract_json_object(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        plain = _unwrap_voice_text(raw)
        if len(plain) >= 20:
            return LessonVoiceScript(slide_idx=expected_idx, script_text=plain)
        raise
    if isinstance(data, str):
        return LessonVoiceScript(slide_idx=expected_idx, script_text=_unwrap_voice_text(data))
    if not isinstance(data, dict):
        raise ValueError("음성대본 응답이 객체가 아니다.")
    if "voice_scripts" in data:
        scripts = data["voice_scripts"]
        if not isinstance(scripts, list) or not scripts:
            raise ValueError("voice_scripts 배열이 비어 있다.")
        data = scripts[0]
    if "voice_script" in data and isinstance(data["voice_script"], dict):
        data = data["voice_script"]
    script = LessonVoiceScript.model_validate(data)
    if script.slide_idx != expected_idx:
        raise ValueError(f"음성대본 slide_idx 불일치: expected={expected_idx}, actual={script.slide_idx}")
    return script


def _voice_response_to_segment(text: str, expected_slide_idx: int, expected_segment_idx: int) -> tuple[LessonVoiceSegment | None, str]:
    try:
        return _parse_single_voice_segment(text, expected_slide_idx, expected_segment_idx), ""
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _parse_single_voice_segment(text: str, expected_slide_idx: int, expected_segment_idx: int) -> LessonVoiceSegment:
    raw = _extract_json_object(text)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("음성대본 문단 응답이 객체가 아니다.")
    if "voice_segment" in data and isinstance(data["voice_segment"], dict):
        data = data["voice_segment"]
    if "segment_text" not in data and "script_text" in data:
        data = {**data, "segment_text": data["script_text"]}
    segment = LessonVoiceSegment.model_validate(data)
    if segment.slide_idx != expected_slide_idx:
        raise ValueError(f"문단 slide_idx 불일치: expected={expected_slide_idx}, actual={segment.slide_idx}")
    if segment.segment_idx != expected_segment_idx:
        raise ValueError(f"문단 segment_idx 불일치: expected={expected_segment_idx}, actual={segment.segment_idx}")
    return segment


def _unwrap_voice_text(value: str) -> str:
    text = value.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return text.replace("\\n", " ").replace('\\"', '"').strip()


def _combine_voice_text(base: str, addition: str) -> str:
    base_text = base.strip()
    addition_text = _unwrap_voice_text(addition)
    if not base_text:
        return addition_text
    if len(addition_text) > len(base_text) and base_text[:80] in addition_text:
        return addition_text
    if addition_text in base_text:
        return base_text
    return f"{base_text} {addition_text}".strip()


def _merge_voice_segments(segments: list[str]) -> str:
    pieces: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        text = _unwrap_voice_text(segment)
        if not text:
            continue
        normalized = re.sub(r"\s+", " ", text).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        pieces.append(normalized)
    return " ".join(pieces).strip()


def _voice_raw_record(stage: str, slide_idx: int, response: ChapterAIResponse, note: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "slide_idx": slide_idx,
        "model": response.model,
        "finish_reason": response.finish_reason,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "note": note,
        "text": response.text,
    }


def _voice_script_needs_retry(text: str) -> bool:
    return not (
        VOICE_TARGET_MIN_CHARS <= len(text.strip()) <= VOICE_TARGET_MAX_CHARS
        and 8 <= _tts_sentence_count(text) <= 60
        and _is_tts_script(text)
        and _is_detailed_tutor_script(text)
        and _has_tts_delivery_style(text)
        and _ngram_repetition_ratio(text) <= 0.30
    )


def _voice_script_quality_note(text: str) -> str:
    checks = {
        "chars": len(text.strip()),
        "sentences": _tts_sentence_count(text),
        "tts_safe": _is_tts_script(text),
        "depth": _is_detailed_tutor_script(text),
        "delivery": _has_tts_delivery_style(text),
        "repeat_ratio": round(_ngram_repetition_ratio(text), 3),
    }
    return json.dumps(checks, ensure_ascii=False)


def _voice_quality_score(text: str) -> int:
    score = 0
    stripped = text.strip()
    score += 2 if VOICE_TARGET_MIN_CHARS <= len(stripped) <= VOICE_TARGET_MAX_CHARS else 0
    score += 1 if 8 <= _tts_sentence_count(stripped) <= 60 else 0
    score += 2 if _is_detailed_tutor_script(stripped) else 0
    score += 1 if _is_tts_script(stripped) else 0
    score += 2 if _has_tts_delivery_style(stripped) else 0
    score += 1 if _ngram_repetition_ratio(stripped) <= 0.30 else 0
    return score


def _apply_voice_expansion_meta(
    meta: dict[str, Any],
    responses: list[ChapterAIResponse],
    wall_sec: float,
    remaining_retry_targets: list[tuple[LessonSlide, str]],
) -> None:
    input_tokens = sum(response.input_tokens for response in responses)
    output_tokens = sum(response.output_tokens for response in responses)
    meta["voice_expansion"] = {
        "model": responses[0].model if responses else "",
        "calls": len(responses),
        "finish_reasons": [response.finish_reason for response in responses],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "wall_sec": wall_sec,
        "remaining_retry_targets": [
            {"slide_idx": slide.slide_idx, "reason": reason}
            for slide, reason in remaining_retry_targets
        ],
    }
    meta["input_tokens"] = int(meta["input_tokens"]) + input_tokens
    meta["output_tokens"] = int(meta["output_tokens"]) + output_tokens
    meta["wall_sec"] = float(meta["wall_sec"]) + wall_sec
    meta["estimated_b200_gpu_cost_usd"] = float(meta["wall_sec"]) * B200_USD_PER_SEC
    meta["estimated_b200_gpu_cost_with_scaledown_usd"] = (float(meta["wall_sec"]) + SCALEDOWN_WINDOW_SEC) * B200_USD_PER_SEC


async def _repair_supporting_materials(
    payload: LessonPayload,
    *,
    out_dir: Path,
    meta: dict[str, Any],
    weak_points: str,
    reference_context_prompt: str,
) -> LessonPayload:
    started = time.perf_counter()
    request = ChapterAIRequest(
        system=_supporting_repair_system(len(payload.slides)),
        user=_supporting_repair_user(payload, weak_points=weak_points, reference_context_prompt=reference_context_prompt),
        max_tokens=9000,
        temperature=0,
        extra={"slide_count": len(payload.slides), "schema": "supporting_materials", "supporting_repair": True, "seed": 907},
    )
    response = await Qwen27BModalConnector().generate(request)
    wall_sec = time.perf_counter() - started
    _write_text(out_dir / "raw_supporting_repair_response.txt", response.text)
    repaired = _parse_supporting_repair(response.text, len(payload.slides))
    _apply_supporting_repair_meta(meta, response, wall_sec)
    return payload.model_copy(update={"quizzes": repaired.quizzes, "assignment": repaired.assignment})


def _supporting_repair_system(slide_count: int) -> str:
    return (
        "너는 ChapterStudio_V1의 퀴즈와 과제 보강기다. 출력은 단일 JSON 객체 한 개뿐이다. "
        "JSON 외 텍스트, 사고과정, markdown fence, <think> 블록을 금지한다. "
        "최상위 키는 정확히 quizzes, assignment 두 개뿐이다. "
        f"quizzes는 정확히 {slide_count}개이며 slide_idx는 0부터 {slide_count - 1}까지 정확히 한 번씩 쓴다. "
        "각 quiz는 slide_idx, question, choices, answer_idx, difficulty, explanation만 가진다. "
        "assignment는 title, assignment_format, expected_minutes, steps, rubric만 가진다. "
        "모든 quiz explanation과 assignment steps/rubric 항목에는 약점 연결 또는 평가 기준 표현과 취약점 핵심어를 정확히 포함한다."
    )


def _supporting_repair_user(payload: LessonPayload, *, weak_points: str, reference_context_prompt: str) -> str:
    core_terms = ", ".join(_prompt_weak_terms(weak_points))
    slide_lines = [
        f"{slide.slide_idx}. title={slide.title} / focus={slide.focus} / checkpoint={slide.checkpoint}"
        for slide in payload.slides
    ]
    return (
        f"취약점: {weak_points}\n"
        f"반드시 그대로 넣을 취약점 핵심어 목록: {core_terms}\n"
        f"{reference_context_prompt}\n"
        "목표: 기존 슬라이드 15장을 바꾸지 않고, 퀴즈와 과제만 사용자 약점 맞춤형으로 다시 작성한다.\n"
        "모든 quiz.explanation은 120~180자이며 '오답 함정:'과 '약점 연결:'을 둘 다 포함한다. "
        f"각 quiz.explanation에는 취약점 핵심어 목록({core_terms}) 중 최소 1개를 정확한 문자열로 넣는다. "
        "성능지표를 말할 때는 반드시 '정확도만' 또는 '혼동행렬' 또는 'FP' 또는 'FN'을 함께 넣는다. "
        "시간 배분이나 체크리스트를 말할 때도 반드시 '전처리', '모델링', '해석' 중 최소 1개를 함께 넣는다. "
        "assignment.expected_minutes는 반드시 30 정수로 쓴다. 30이 아닌 값은 실패다. "
        "assignment.steps와 assignment.rubric은 각각 3~4개만 쓴다. "
        "assignment steps와 rubric의 모든 항목에는 p.번호, '약점 교정:' 또는 '평가 기준:', 취약점 핵심어 목록 중 최소 1개를 정확히 넣는다. "
        "기존 슬라이드 목록:\n" + "\n".join(slide_lines)
    )


def _parse_supporting_repair(text: str, slide_count: int) -> SupportingRepairPayload:
    raw = _extract_json_object(text)
    try:
        payload = SupportingRepairPayload.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError(f"지원 산출물 보강 JSON 검증 실패: {exc}") from exc
    expected = set(range(slide_count))
    quiz_idx = {quiz.slide_idx for quiz in payload.quizzes}
    if quiz_idx != expected:
        raise ValueError(f"지원 산출물 quiz slide_idx 불일치: {quiz_idx}")
    return payload


def _apply_supporting_repair_meta(meta: dict[str, Any], response: ChapterAIResponse, wall_sec: float) -> None:
    meta["supporting_repair"] = {
        "model": response.model,
        "finish_reason": response.finish_reason,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "wall_sec": wall_sec,
    }
    meta["input_tokens"] = int(meta["input_tokens"]) + response.input_tokens
    meta["output_tokens"] = int(meta["output_tokens"]) + response.output_tokens
    meta["wall_sec"] = float(meta["wall_sec"]) + wall_sec
    meta["estimated_b200_gpu_cost_usd"] = float(meta["wall_sec"]) * B200_USD_PER_SEC
    meta["estimated_b200_gpu_cost_with_scaledown_usd"] = (float(meta["wall_sec"]) + SCALEDOWN_WINDOW_SEC) * B200_USD_PER_SEC


def _extract_json_object(text: str) -> str:
    stripped = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    stripped = re.sub(r"<think>.*", "", stripped, flags=re.DOTALL)
    if "</think>" in stripped:
        stripped = stripped.rsplit("</think>", 1)[-1]
    stripped = re.sub(r"```(?:json)?", "", stripped).strip()
    start = stripped.find("{")
    if start == -1:
        return stripped
    depth = 0
    in_string = False
    escape_next = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if escape_next:
            escape_next = False
            continue
        if char == "\\" and in_string:
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start:index + 1]
    return stripped[start:]


def _slide_inputs(payload: LessonPayload) -> list[SlideInput]:
    return [
        {"index": slide.slide_idx, "category": slide.category, "html": slide.html, "css": slide.css}
        for slide in payload.slides
    ]


def _result(
    payload: LessonPayload,
    processed: list[PostprocessResult],
    *,
    reference_pages: list[int],
    learner_profile: str,
    weak_points: str,
) -> dict[str, Any]:
    processed_by_idx = {int(item["index"]): item for item in processed}
    return {
        "topic": "빅데이터 분석기사 필기 실전 연결 강의",
        "learner_profile": learner_profile,
        "weak_points": weak_points,
        "slides": [
            {
                "slide_idx": slide.slide_idx,
                "title": slide.title,
                "focus": slide.focus,
                "checkpoint": slide.checkpoint,
                "category": slide.category,
                "iframe_html": iframe_srcdoc(str(processed_by_idx[slide.slide_idx]["iframe_html"])),
                "warnings": processed_by_idx[slide.slide_idx]["warnings"],
            }
            for slide in payload.slides
        ],
        "quizzes": [quiz.model_dump() for quiz in payload.quizzes],
        "note_blocks": [block.model_dump() for block in payload.note_blocks],
        "assignment": payload.assignment.model_dump(),
        "voice_scripts": [script.model_dump() for script in payload.voice_scripts],
        "storage_preview": [
            {"table": "chapter_studio.slide", "rows": len(payload.slides), "note": "iframeHtml srcDoc 문서 HTML"},
            {"table": "chapter_studio.quiz", "rows": len(payload.quizzes), "note": "슬라이드별 평가 문항"},
            {"table": "chapter_studio.note", "rows": 1, "note": f"핵심정리 블록 {len(payload.note_blocks)}개"},
            {"table": "chapter_studio.assignment", "rows": 1, "note": "과제 형식, 예상 시간, 절차, rubric"},
            {"table": "chapter_studio.voice_script", "rows": len(payload.voice_scripts), "note": "슬라이드별 TTS 대본"},
            {"table": "chapter_studio.voice_script_queue", "rows": len(payload.voice_scripts), "note": "TTS 비동기 큐"},
        ],
        "reference_pages": reference_pages,
    }


def _score(
    payload: dict[str, Any] | None,
    result: dict[str, Any] | None,
    parse_error: str,
    warnings: list[str],
    slide_count: int,
    meta: dict[str, Any],
    weak_points: str,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    _add(items, "schema", "JSON 스키마·파싱", 15, 0 if parse_error else 15, parse_error or "파싱 성공")
    if payload is None or result is None:
        return {"total": _total(items), "pass": False, "items": items, "critical_failures": [parse_error]}
    _add_pair(items, "scale_contract", "실전 강의 규모 계약", 15, _score_scale_contract(result, slide_count))
    _add_pair(items, "slides", "10~15장 슬라이드 품질", 20, _score_slides(result, slide_count))
    _add_pair(items, "personalization", "사용자 약점 맞춤 반영", 15, _score_personalization(result, weak_points, slide_count))
    _add_pair(items, "visual_variety", "시각자료 다양성", 10, _score_visual_variety(result))
    _add_pair(items, "voice", "TTS 과외 대본", 15, _score_voice(result, slide_count))
    _add_pair(items, "notes", "핵심정리 노트", 10, _score_notes(result))
    _add_pair(items, "assignment", "과제 형식·루브릭", 10, _score_assignment(result))
    _add_pair(items, "quizzes", "슬라이드별 퀴즈", 10, _score_quizzes(result, slide_count))
    _add_pair(items, "references", "참고도서 OCR 페이지 활용", 10, _score_references(result))
    _add_pair(items, "safety", "렌더·보안 안전성", 10, _score_safety(payload, result))
    _add_pair(items, "postprocess", "후처리 경고", 5, _score_postprocess(warnings))
    _add_pair(items, "ops", "시간·비용 운영성", 10, _score_ops(meta))
    critical_keys = {"schema", "scale_contract", "personalization", "visual_variety", "references", "safety", "postprocess"}
    critical = [item["label"] for item in items if item["key"] in critical_keys and item["score"] < item["max_score"]]
    total = _total(items)
    return {"total": total, "pass": total >= PASS_SCORE and not critical, "items": items, "critical_failures": critical}


def _score_scale_contract(result: dict[str, Any], slide_count: int) -> tuple[int, str]:
    slide_idx = sorted(int(slide.get("slide_idx", -1)) for slide in result.get("slides", []))
    voice_idx = sorted(int(script.get("slide_idx", -1)) for script in result.get("voice_scripts", []))
    quizzes = result.get("quizzes", [])
    quiz_idx = sorted(int(quiz.get("slide_idx", -1)) for quiz in quizzes)
    notes = result.get("note_blocks", [])
    expected = list(range(slide_count))
    storage_tables = {str(item.get("table", "")) for item in result.get("storage_preview", [])}
    storage_ok = {"chapter_studio.slide", "chapter_studio.quiz", "chapter_studio.note", "chapter_studio.assignment", "chapter_studio.voice_script", "chapter_studio.voice_script_queue"}.issubset(storage_tables)
    score = 0
    score += 4 if slide_idx == expected else 0
    score += 4 if voice_idx == expected else 0
    score += 3 if quiz_idx == expected else 0
    score += 2 if 3 <= len(notes) <= 5 else 0
    score += 2 if storage_ok else 0
    return score, f"slides={len(slide_idx)}, voices={len(voice_idx)}, quizzes={len(quizzes)} idx={quiz_idx == expected}, notes={len(notes)}, storage={storage_ok}"


def _score_slides(result: dict[str, Any], slide_count: int) -> tuple[int, str]:
    slides = result.get("slides", [])
    html_values = [_strip_style(str(slide.get("iframe_html", ""))) for slide in slides]
    meaningful = sum(_has_meaningful_visual(value) for value in html_values)
    sentence_ok = sum(_slide_sentence_ok(slide, html) for slide, html in zip(slides, html_values, strict=False))
    title_ok = sum(bool(str(slide.get("title", "")).strip()) for slide in slides)
    category_count = len({str(slide.get("category", "")) for slide in slides})
    score = 0
    score += 5 if len(slides) == slide_count else 0
    score += min(7, meaningful * 7 // max(1, slide_count))
    score += 4 if sentence_ok >= max(1, slide_count - 1) else min(4, sentence_ok * 4 // max(1, slide_count))
    score += min(2, title_ok * 2 // max(1, slide_count))
    score += min(2, category_count // 2)
    return min(20, score), f"시각단서 {meaningful}/{slide_count}, 시각형 문장량 {sentence_ok}/{slide_count}, 카테고리 {category_count}종"


def _slide_sentence_ok(slide: object, html: str) -> bool:
    if not isinstance(slide, dict):
        return False
    sentence_count = _sentence_count(html)
    category = str(slide.get("category", ""))
    upper = 14 if category == "code" else 10 if _has_structured_visual(html) else 8
    return 2 <= sentence_count <= upper


def _has_structured_visual(html: str) -> bool:
    return any(marker in html for marker in ("flow-strip", "timeline", "step-grid", "comparison-table", "linked-list", "graph-map"))


def _score_personalization(result: dict[str, Any], weak_points: str, slide_count: int) -> tuple[int, str]:
    terms = _weak_terms(weak_points)
    slides = result.get("slides", [])
    scripts = result.get("voice_scripts", [])
    quizzes = result.get("quizzes", [])
    note_bullets = [str(bullet) for block in result.get("note_blocks", []) for bullet in block.get("bullets", [])]
    assignment = result.get("assignment", {})
    assignment_texts = [*map(str, assignment.get("steps", [])), *map(str, assignment.get("rubric", []))]
    slide_hits = sum(
        _has_weakness_marker(" ".join(str(slide.get(key, "")) for key in ("title", "focus", "checkpoint", "iframe_html")), terms)
        for slide in slides
    )
    voice_hits = sum(_has_weakness_marker(str(script.get("script_text", "")), terms) for script in scripts)
    quiz_hits = sum(_has_weakness_marker(str(quiz.get("question", "")) + " " + str(quiz.get("explanation", "")), terms) for quiz in quizzes)
    note_hits = sum(_has_weakness_marker(text, terms) for text in note_bullets)
    assignment_hits = sum(_has_weakness_marker(text, terms) for text in assignment_texts)
    score = 0
    score += min(4, slide_hits * 4 // max(1, slide_count))
    score += min(4, voice_hits * 4 // max(1, slide_count))
    score += min(3, quiz_hits * 3 // max(1, slide_count))
    score += min(2, note_hits)
    score += min(2, assignment_hits)
    note = (
        f"약점키워드={terms[:8]}, 슬라이드 {slide_hits}/{slide_count}, 대본 {voice_hits}/{slide_count}, "
        f"퀴즈 {quiz_hits}/{slide_count}, 노트 {note_hits}, 과제 {assignment_hits}"
    )
    return min(15, score), note


def _score_visual_variety(result: dict[str, Any]) -> tuple[int, str]:
    html_text = "\n".join(_strip_style(str(slide.get("iframe_html", ""))) for slide in result.get("slides", []))
    checks = {
        "chart": "rendered-chart" in html_text and "data:image/png" in html_text,
        "diagram": "mermaid-fallback" in html_text or "<svg" in html_text,
        "code": "code-card" in html_text and "tok-" in html_text,
        "formula": "formula" in html_text,
        "interactive": "<details" in html_text,
        "table_or_grid": "<table" in html_text or "comparison-table" in html_text or "step-grid" in html_text,
    }
    raw_failures = _has_raw_visual_source(html_text)
    score = sum(2 for value in checks.values() if value)
    if raw_failures:
        score = min(score, 8)
    return min(10, score), f"{checks}, raw_visual={raw_failures}"


def _score_voice(result: dict[str, Any], slide_count: int) -> tuple[int, str]:
    scripts = result.get("voice_scripts", [])
    sentence_ok = sum(8 <= _tts_sentence_count(str(item.get("script_text", ""))) <= 60 for item in scripts)
    tts_ok = sum(_is_tts_script(str(item.get("script_text", ""))) for item in scripts)
    depth_ok = sum(_is_detailed_tutor_script(str(item.get("script_text", ""))) for item in scripts)
    delivery_ok = sum(_has_tts_delivery_style(str(item.get("script_text", ""))) for item in scripts)
    repeat_ok = sum(_ngram_repetition_ratio(str(item.get("script_text", ""))) <= 0.30 for item in scripts)
    ref_count = _count_refs([str(item.get("script_text", "")) for item in scripts])
    score = (
        (2 if len(scripts) == slide_count else 0)
        + min(3, sentence_ok * 3 // max(1, slide_count))
        + min(4, depth_ok * 4 // max(1, slide_count))
        + min(2, tts_ok * 2 // max(1, slide_count))
        + min(3, delivery_ok * 3 // max(1, slide_count))
        + min(1, ref_count)
    )
    return min(15, score), f"대본 {len(scripts)}개, 8~60문장 {sentence_ok}/{slide_count}, 깊이 {depth_ok}/{slide_count}, TTS안전 {tts_ok}/{slide_count}, 말투·발음 {delivery_ok}/{slide_count}, 반복억제 {repeat_ok}/{slide_count}, p.참조 {ref_count}"


def _tts_sentence_count(text: str) -> int:
    """페이지 표기 p.7의 마침표를 문장 경계로 오판하지 않게 한다."""
    normalized = re.sub(r"\bp\.(\d+)", r"p\1", text)
    return _sentence_count(normalized)


def _score_notes(result: dict[str, Any]) -> tuple[int, str]:
    notes = result.get("note_blocks", [])
    bullets = [str(bullet) for block in notes for bullet in block.get("bullets", [])]
    depth_ok = sum(len(bullet) >= 45 for bullet in bullets)
    ref_count = _count_refs(bullets)
    score = (3 if 3 <= len(notes) <= 5 else 0) + min(4, depth_ok) + min(3, ref_count)
    return min(10, score), f"블록 {len(notes)}개, 깊이 bullet {depth_ok}, p.참조 {ref_count}"


def _score_assignment(result: dict[str, Any]) -> tuple[int, str]:
    assignment = result.get("assignment", {})
    steps = assignment.get("steps", [])
    rubric = assignment.get("rubric", [])
    expected_minutes = assignment.get("expected_minutes")
    action_ok = sum(bool(_ACTION_RE.search(str(step))) for step in steps)
    ref_count = _count_refs([*map(str, steps), *map(str, rubric)])
    score = (
        (2 if str(assignment.get("assignment_format", "")).strip() else 0)
        + (2 if isinstance(expected_minutes, int) and 20 <= expected_minutes <= 40 else 0)
        + (2 if 3 <= len(steps) <= 5 else 0)
        + (2 if 3 <= len(rubric) <= 5 else 0)
        + min(1, action_ok)
        + min(1, ref_count)
    )
    return min(10, score), f"format={bool(str(assignment.get('assignment_format', '')).strip())}, minutes={expected_minutes}, steps={len(steps)}, rubric={len(rubric)}, refs={ref_count}"


def _score_quizzes(result: dict[str, Any], slide_count: int) -> tuple[int, str]:
    quizzes = result.get("quizzes", [])
    expected = list(range(slide_count))
    quiz_idx = sorted(int(item.get("slide_idx", -1)) for item in quizzes)
    choices_ok = sum(len(item.get("choices", [])) == 4 for item in quizzes)
    explanation_ok = sum(len(str(item.get("explanation", ""))) >= 70 for item in quizzes)
    difficulty_ok = len({str(item.get("difficulty", "")) for item in quizzes}) >= 3
    score = (3 if quiz_idx == expected else 0) + min(3, choices_ok * 3 // max(1, slide_count)) + min(3, explanation_ok * 3 // max(1, slide_count)) + (1 if difficulty_ok else 0)
    return min(10, score), f"문항 {len(quizzes)}개, slide_idx={quiz_idx == expected}, 선택지4개 {choices_ok}, 해설충분 {explanation_ok}, 난이도분산={difficulty_ok}"


def _score_references(result: dict[str, Any]) -> tuple[int, str]:
    note_text = " ".join(str(bullet) for block in result.get("note_blocks", []) for bullet in block.get("bullets", []))
    voice_text = " ".join(str(item.get("script_text", "")) for item in result.get("voice_scripts", []))
    assignment_text = " ".join(map(str, result.get("assignment", {}).get("steps", [])))
    allowed_pages = {int(page) for page in result.get("reference_pages", []) if isinstance(page, int)}
    referenced_pages = _extract_ref_pages([note_text, voice_text, assignment_text])
    note_refs = _count_refs([note_text])
    voice_refs = _count_refs([voice_text])
    assignment_refs = _count_refs([assignment_text])
    score = min(4, note_refs) + min(3, voice_refs) + min(3, assignment_refs)
    unknown_pages = sorted(referenced_pages - allowed_pages) if allowed_pages else []
    if unknown_pages:
        score = min(score, 8)
    note = f"노트 {note_refs}, 대본 {voice_refs}, 과제 {assignment_refs}, OCR페이지 {sorted(allowed_pages)}"
    if unknown_pages:
        note += f", 미검증 페이지 {unknown_pages}"
    return min(10, score), note


def _score_safety(payload: dict[str, Any], result: dict[str, Any]) -> tuple[int, str]:
    raw_html = "\n".join(str(slide.get("html", "")) + "\n" + str(slide.get("css", "")) for slide in payload.get("slides", []))
    iframe_html = "\n".join(str(slide.get("iframe_html", "")) for slide in result.get("slides", []))
    has_script = bool(re.search(r"<\s*script", raw_html, re.I))
    has_external = bool(re.search(r"https?://|//[a-z0-9.-]+", raw_html, re.I))
    has_event_handler = bool(re.search(r"\son[a-z]+\s*=", raw_html, re.I))
    has_js_url = bool(re.search(r"javascript:|data:text/html", raw_html, re.I))
    has_fence = "```" in raw_html
    iframe_doc_ok = iframe_html.count("<!DOCTYPE html>") == len(result.get("slides", [])) and "<iframe" not in iframe_html.lower()
    score = (2 if not has_script else 0) + (2 if not has_external else 0) + (2 if not has_event_handler else 0) + (1 if not has_js_url else 0) + (1 if not has_fence else 0) + (2 if iframe_doc_ok else 0)
    return score, f"script={has_script}, external_url={has_external}, event_handler={has_event_handler}, js_url={has_js_url}, fence={has_fence}, iframe_doc={iframe_doc_ok}"


def _score_postprocess(warnings: list[str]) -> tuple[int, str]:
    if not warnings:
        return 5, "후처리 경고 없음"
    return max(0, 5 - len(warnings)), "; ".join(warnings[:5])


def _score_ops(meta: dict[str, Any]) -> tuple[int, str]:
    wall_sec = float(meta["wall_sec"])
    cost = float(meta["estimated_b200_gpu_cost_usd"])
    cost_with_scaledown = float(meta["estimated_b200_gpu_cost_with_scaledown_usd"])
    score = (4 if wall_sec <= 900 else 2 if wall_sec <= 1200 else 0) + (3 if cost <= 1.75 else 1 if cost <= 2.50 else 0) + (3 if cost_with_scaledown <= 2.00 else 1 if cost_with_scaledown <= 2.75 else 0)
    return score, f"wall={wall_sec:.1f}s, gpu=${cost:.4f}, +scaledown=${cost_with_scaledown:.4f}"


def _response_meta(
    run_id: str,
    response: ChapterAIResponse,
    wall_sec: float,
    slide_count: int,
    *,
    learner_profile: str,
    weak_points: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "model": response.model,
        "finish_reason": response.finish_reason,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "wall_sec": wall_sec,
        "slide_count": slide_count,
        "learner_profile": learner_profile,
        "weak_points": weak_points,
        "b200_usd_per_sec": B200_USD_PER_SEC,
        "estimated_b200_gpu_cost_usd": wall_sec * B200_USD_PER_SEC,
        "estimated_b200_gpu_cost_with_scaledown_usd": (wall_sec + SCALEDOWN_WINDOW_SEC) * B200_USD_PER_SEC,
        "scaledown_window_sec": SCALEDOWN_WINDOW_SEC,
        "manual_correction": False,
        "pricing_source": "https://modal.com/pricing",
    }


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


def _meta_model(meta_path: Path | None) -> str:
    if meta_path is None or not meta_path.exists():
        return "Qwen/Qwen3.6-27B"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return str(meta.get("model", "Qwen/Qwen3.6-27B")) if isinstance(meta, dict) else "Qwen/Qwen3.6-27B"


def _meta_from_existing(meta_path: Path, run_id: str, learner_profile: str, weak_points: str) -> dict[str, Any]:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        raise ValueError("기존 meta 파일이 객체가 아니다.")
    updated = dict(meta)
    updated["run_id"] = run_id
    updated["learner_profile"] = learner_profile
    updated["weak_points"] = weak_points
    updated["manual_correction"] = False
    return updated


def _report_html(
    run_id: str,
    meta: dict[str, Any],
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
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>ChapterStudio Actual Lesson Report</title>
<style>
:root{{color-scheme:light dark;--bg:#F8F8F6;--paper:#FFFFFF;--ink:#182229;--muted:#607078;--line:#D9DED8}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,Pretendard,system-ui,-apple-system,sans-serif;line-height:1.55}}
main{{max-width:1180px;margin:0 auto;padding:28px}} h1{{margin:0;font-size:28px;letter-spacing:0}} h2{{margin:28px 0 12px;font-size:18px}} h3{{margin:0 0 8px;font-size:15px}}
.top{{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:end;border-bottom:1px solid var(--line);padding-bottom:18px}}
.badge{{display:inline-grid;place-items:center;min-width:92px;height:46px;border-radius:8px;background:{'#207B4C' if scorecard['pass'] else '#A33A3A'};color:white;font-weight:800}}
.score{{font-size:44px;font-weight:900}} .meta{{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}} .chip{{padding:5px 9px;border:1px solid var(--line);border-radius:999px;background:var(--paper);color:#43525A;font-size:12px}}
table{{width:100%;border-collapse:collapse;background:var(--paper);border:1px solid var(--line);border-radius:8px;overflow:hidden}} td,th{{border-bottom:1px solid #E6EAE6;padding:10px 12px;text-align:left;vertical-align:top}} tr:last-child td{{border-bottom:0}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}} .panel{{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:14px}} .slide iframe{{width:100%;min-height:420px;border:1px solid #CFD8CF;border-radius:8px;background:white}}
pre{{white-space:pre-wrap;background:#172026;color:#F8F8F6;padding:12px;border-radius:8px;max-height:360px;overflow:auto}} .small{{color:var(--muted);font-size:13px}} .notice{{background:#FFF3DA;border:1px solid #E5D7AF;border-radius:8px;padding:10px 12px}}
@media(max-width:820px){{main{{padding:16px}}.top,.grid{{grid-template-columns:1fr}}}}
@media(prefers-color-scheme:dark){{:root{{--bg:#12191E;--paper:#192228;--ink:#EEF2F5;--muted:#B6C0C6;--line:#33434B}}.chip{{color:var(--muted)}}td,th{{border-bottom-color:#28363D}}}}
</style>
</head>
<body><main>
<section class="top"><div><h1>실전 1강 Modal 품질·비용 리포트</h1><div class="meta">
<span class="chip">run {run_id}</span><span class="chip">{_h(str(meta['model']))}</span><span class="chip">{meta['slide_count']} slides</span>
<span class="chip">latency {float(meta['wall_sec']):.1f}s</span><span class="chip">GPU ${float(meta['estimated_b200_gpu_cost_usd']):.4f}</span><span class="chip">scaledown 포함 ${float(meta['estimated_b200_gpu_cost_with_scaledown_usd']):.4f}</span>
<span class="chip">tokens {meta['input_tokens']} → {meta['output_tokens']}</span></div></div><div><div class="badge">{badge}</div><div class="score">{scorecard['total']}</div></div></section>
<p class="notice">평가 원칙: 모델 응답 원문을 직접 보정하지 않았고, 파싱·후처리·채점 결과를 그대로 기록했다.</p>
{f'<p class="panel"><strong>파싱 실패:</strong> {_h(parse_error)}</p>' if parse_error else ''}
{f'<p class="panel"><strong>후처리 경고:</strong> {_h("; ".join(warnings))}</p>' if warnings else ''}
<h2>점수</h2><table><thead><tr><th>영역</th><th>점수</th><th>근거</th></tr></thead><tbody>{rows}</tbody></table>
{_summary_html(result)}
{_slides_html(result)}
<h2>원본 응답 미리보기</h2><pre>{_h(raw_text[:2400])}</pre>
</main></body></html>"""


def _practical_report_html(
    run_id: str,
    meta: dict[str, Any],
    scorecard: dict[str, Any],
    result: dict[str, Any] | None,
    raw_text: str,
    parse_error: str,
    warnings: list[str],
) -> str:
    badge = "PASS" if scorecard["pass"] else "FAIL"
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>ChapterStudio 실전 1강 산출물 보고서</title>
<style>
:root{{color-scheme:light dark;--bg:#F8F8F6;--paper:#FFFDF7;--ink:#172229;--muted:#52646F;--line:#D7E0DA;--accent:#207B4C;--accent2:#2A5C7A;--warn:#8A5A00;--soft:#EAF3ED;--soft2:#EAF2F7}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,Pretendard,system-ui,-apple-system,sans-serif;line-height:1.6}}
main{{max-width:1280px;margin:0 auto;padding:30px}} h1{{margin:0;font-size:30px;letter-spacing:0}} h2{{margin:32px 0 14px;font-size:21px}} h3{{margin:0 0 8px;font-size:16px}}
.hero{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:18px;align-items:end;padding:24px;border:1px solid var(--line);border-radius:8px;background:linear-gradient(135deg,var(--paper),var(--soft2))}}
.badge{{display:inline-grid;place-items:center;min-width:96px;height:48px;border-radius:8px;background:{'#207B4C' if scorecard['pass'] else '#A33A3A'};color:#FFFFFF;font-weight:900}}
.score{{font-size:46px;font-weight:900;text-align:right}} .chips{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}} .chip{{padding:6px 10px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.72);color:#31444E;font-size:12px;font-weight:700}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}} .wide{{grid-column:1/-1}}
.panel{{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:16px;box-shadow:0 8px 20px rgba(23,34,41,.06)}}
.metric{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:14px}} .metric div{{border:1px solid var(--line);border-radius:8px;background:#FFFFFF;padding:12px}} .metric strong{{display:block;font-size:22px;color:var(--accent)}}
.slide-card{{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr);gap:14px;align-items:start}} iframe{{width:100%;min-height:540px;border:1px solid #BFD0C4;border-radius:8px;background:#FFFFFF}}
.script{{white-space:pre-wrap;background:var(--soft);border-left:5px solid var(--accent);padding:12px;border-radius:8px;color:#182A20}} .quiz{{border-left:5px solid var(--accent2)}} .note{{border-left:5px solid var(--warn)}} ul,ol{{padding-left:22px}} li{{margin:6px 0}} table{{width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid var(--line);border-radius:8px;overflow:hidden}} td,th{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} tr:last-child td{{border-bottom:0}}
pre{{white-space:pre-wrap;background:#172229;color:#F8F8F6;padding:12px;border-radius:8px;max-height:300px;overflow:auto}} .small{{color:var(--muted);font-size:13px}} .fail{{color:#9A2F2F;font-weight:800}}
@media(max-width:920px){{main{{padding:16px}}.hero,.grid,.slide-card,.metric{{grid-template-columns:1fr}}iframe{{min-height:460px}}}}
@media(prefers-color-scheme:dark){{:root{{--bg:#12191E;--paper:#182229;--ink:#F1F5F3;--muted:#B9C5CC;--line:#32444C;--soft:#183025;--soft2:#1B2B35}}.chip,.metric div,table{{background:#10181D;color:var(--ink)}}iframe{{background:#FFFFFF}}}}
</style>
</head>
<body><main>
<section class="hero"><div><h1>맞춤형 실전 1강 산출물 보고서</h1>
<div class="chips"><span class="chip">run {run_id}</span><span class="chip">{_h(str(meta['model']))}</span><span class="chip">1강 {meta['slide_count']}슬라이드</span><span class="chip">원문 무보정</span></div>
<p><strong>학습자:</strong> {_h(str(meta.get('learner_profile', '')))}</p><p><strong>반영해야 할 약점:</strong> {_h(str(meta.get('weak_points', '')))}</p></div><div><div class="badge">{badge}</div><div class="score">{scorecard['total']}</div></div></section>
{_practical_error_html(parse_error, warnings)}
{_practical_metric_html(meta, result)}
{_personalization_html(scorecard, result)}
{_practical_slides_html(result)}
{_practical_notes_html(result)}
{_practical_assignment_html(result)}
<h2>모델 원문</h2><pre>{_h(raw_text[:3600])}</pre>
</main></body></html>"""


def _practical_error_html(parse_error: str, warnings: list[str]) -> str:
    blocks: list[str] = []
    if parse_error:
        blocks.append(f"<article class=\"panel fail\"><h2>파싱 실패</h2><p>{_h(parse_error)}</p></article>")
    if warnings:
        blocks.append(f"<article class=\"panel\"><h2>후처리 경고</h2><p>{_h('; '.join(warnings))}</p></article>")
    return "\n".join(blocks)


def _practical_metric_html(meta: dict[str, Any], result: dict[str, Any] | None) -> str:
    slide_count = len(result.get("slides", [])) if result else 0
    voice_count = len(result.get("voice_scripts", [])) if result else 0
    quiz_count = len(result.get("quizzes", [])) if result else 0
    note_count = len(result.get("note_blocks", [])) if result else 0
    return f"""<section class="metric">
<div><span class="small">생성 시간</span><strong>{float(meta['wall_sec']):.1f}s</strong><span class="small">Modal B200 wall time</span></div>
<div><span class="small">GPU 비용</span><strong>${float(meta['estimated_b200_gpu_cost_usd']):.4f}</strong><span class="small">scaledown 포함 ${float(meta['estimated_b200_gpu_cost_with_scaledown_usd']):.4f}</span></div>
<div><span class="small">토큰</span><strong>{meta['input_tokens']} → {meta['output_tokens']}</strong><span class="small">입력 → 출력</span></div>
<div><span class="small">산출물</span><strong>{slide_count}/{voice_count}/{quiz_count}/{note_count}</strong><span class="small">슬라이드/대본/퀴즈/노트</span></div>
</section>"""


def _personalization_html(scorecard: dict[str, Any], result: dict[str, Any] | None) -> str:
    item = next((entry for entry in scorecard.get("items", []) if entry.get("key") == "personalization"), None)
    note = str(item.get("note", "")) if item else "개별 맞춤 점수 없음"
    score = f"{item.get('score')} / {item.get('max_score')}" if item else "-"
    snippets = ""
    if result:
        rows = []
        for slide in result.get("slides", [])[:6]:
            rows.append(
                "<tr>"
                f"<td>{slide.get('slide_idx')}</td>"
                f"<td>{_h(str(slide.get('title', '')))}</td>"
                f"<td>{_h(str(slide.get('focus', '')))}</td>"
                f"<td>{_h(str(slide.get('checkpoint', '')))}</td>"
                "</tr>"
            )
        snippets = "<table><thead><tr><th>#</th><th>슬라이드</th><th>초점</th><th>체크포인트</th></tr></thead><tbody>" + "\n".join(rows) + "</tbody></table>"
    return f"""<h2>약점 맞춤 검증</h2>
<section class="panel"><p><strong>점수:</strong> {score}</p><p>{_h(note)}</p>{snippets}</section>"""


def _practical_slides_html(result: dict[str, Any] | None) -> str:
    if result is None:
        return ""
    scripts = {int(script.get("slide_idx", -1)): str(script.get("script_text", "")) for script in result.get("voice_scripts", [])}
    quizzes = {int(quiz.get("slide_idx", -1)): quiz for quiz in result.get("quizzes", [])}
    blocks = []
    for slide in result.get("slides", []):
        idx = int(slide.get("slide_idx", -1))
        quiz = quizzes.get(idx, {})
        choices = "".join(f"<li>{_h(str(choice))}</li>" for choice in quiz.get("choices", []))
        slide_frame = _slide_frame(str(slide.get("iframe_html", "")))
        blocks.append(
            f"""<article class="panel wide slide-card">
<div><h3>{idx + 1}. {_h(str(slide.get('title', '')))} <span class="small">({_h(str(slide.get('category', '')))}형)</span></h3>{slide_frame}</div>
<aside><p><strong>초점:</strong> {_h(str(slide.get('focus', '')))}</p><p><strong>자가점검:</strong> {_h(str(slide.get('checkpoint', '')))}</p>
<h3>음성 대본</h3><p class="script">{_h(scripts.get(idx, ''))}</p>
<h3>슬라이드 퀴즈</h3><div class="panel quiz"><p><strong>{_h(str(quiz.get('question', '')))}</strong></p><ol>{choices}</ol><p class="small">정답 {int(quiz.get('answer_idx', 0)) + 1} · {_h(str(quiz.get('difficulty', '')))}</p><p>{_h(str(quiz.get('explanation', '')))}</p></div></aside>
</article>"""
        )
    return "<h2>실전 강의 화면 · 대본 · 퀴즈</h2><section class=\"grid\">" + "\n".join(blocks) + "</section>"


def _practical_notes_html(result: dict[str, Any] | None) -> str:
    if result is None:
        return ""
    blocks = []
    for block in result.get("note_blocks", []):
        bullets = "".join(f"<li>{_h(str(bullet))}</li>" for bullet in block.get("bullets", []))
        blocks.append(f"<article class=\"panel note\"><h3>{_h(str(block.get('heading', '')))}</h3><ul>{bullets}</ul></article>")
    return "<h2>핵심정리 노트</h2><section class=\"grid\">" + "\n".join(blocks) + "</section>"


def _practical_assignment_html(result: dict[str, Any] | None) -> str:
    if result is None:
        return ""
    assignment = result.get("assignment", {})
    steps = "".join(f"<li>{_h(str(step))}</li>" for step in assignment.get("steps", []))
    rubric = "".join(f"<li>{_h(str(item))}</li>" for item in assignment.get("rubric", []))
    return f"""<h2>과제</h2><section class="panel">
<h3>{_h(str(assignment.get('title', '')))}</h3>
<p><strong>형식:</strong> {_h(str(assignment.get('assignment_format', '')))} · <strong>예상:</strong> {assignment.get('expected_minutes')}분</p>
<div class="grid"><article><h3>수행 절차</h3><ol>{steps}</ol></article><article><h3>평가 기준</h3><ul>{rubric}</ul></article></div>
</section>"""


def _summary_html(result: dict[str, Any] | None) -> str:
    if result is None:
        return ""
    assignment = result.get("assignment", {})
    return (
        "<h2>산출물 구조</h2><section class=\"grid\">"
        f"<article class=\"panel\"><h3>강의 산출물</h3><p>슬라이드 {len(result.get('slides', []))}개, 대본 {len(result.get('voice_scripts', []))}개, 퀴즈 {len(result.get('quizzes', []))}개, 핵심노트 {len(result.get('note_blocks', []))}블록</p></article>"
        f"<article class=\"panel\"><h3>{_h(str(assignment.get('title', '과제')))}</h3><p>형식: {_h(str(assignment.get('assignment_format', '')))} · 예상 {assignment.get('expected_minutes')}분 · steps {len(assignment.get('steps', []))}개 · rubric {len(assignment.get('rubric', []))}개</p></article>"
        "</section>"
    )


def _slides_html(result: dict[str, Any] | None) -> str:
    if result is None:
        return ""
    blocks = []
    for slide in result.get("slides", []):
        blocks.append(
            f"<article class=\"panel slide\"><h3>{slide['slide_idx']}. {_h(str(slide['title']))} <span class=\"small\">({_h(str(slide['category']))})</span></h3>{_slide_frame(str(slide['iframe_html']))}<p class=\"small\">{_h(str(slide['focus']))} · {_h(str(slide['checkpoint']))}</p></article>"
        )
    return "<h2>슬라이드 렌더 미리보기</h2><section class=\"grid\">" + "\n".join(blocks) + "</section>"


def _slide_frame(srcdoc: str) -> str:
    return f'<iframe sandbox="allow-scripts" loading="lazy" srcdoc="{_h(srcdoc)}"></iframe>'


def _weak_terms(weak_points: str) -> list[str]:
    seeds = re.split(r"[,;/\n]|·", weak_points)
    terms: list[str] = []
    for seed in seeds:
        cleaned = seed.strip().lower()
        for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", cleaned):
            terms.extend(_term_variants(token.lower()))
    fallback = ["약점", "오답", "함정", "헷갈"]
    return _dedupe([term for term in terms if term and term not in _WEAK_STOPWORDS] or fallback)


def _term_variants(token: str) -> list[str]:
    variants = [token]
    for suffix in ("에서", "에게", "으로", "보다", "처럼", "까지", "부터", "만", "을", "를", "은", "는", "이", "가", "의", "에"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            variants.append(token[: -len(suffix)])
    return variants


def _prompt_weak_terms(weak_points: str) -> list[str]:
    preferred = ["혼동행렬", "FP", "FN", "과대적합", "전처리", "모델링", "해석", "성능지표", "정확도"]
    lower = weak_points.lower()
    terms = [term for term in preferred if term.lower() in lower or (term in {"FP", "FN"} and term.lower() in _weak_terms(weak_points))]
    return terms or _weak_terms(weak_points)[:8]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _has_weakness_marker(text: str, terms: list[str]) -> bool:
    normalized = text.lower()
    term_hit = any(term in normalized for term in terms)
    marker_hit = bool(re.search(r"(약점|취약|오답|함정|헷갈|주의|교정|평가 기준|실수|반대로|정확도만)", normalized))
    return term_hit and marker_hit


def _strip_style(value: str) -> str:
    return re.sub(r"<style\b[^>]*>.*?</style>", "", value, flags=re.DOTALL | re.IGNORECASE)


def _plain_text(value: str) -> str:
    without_style = _strip_style(value)
    without_tags = re.sub(r"<[^>]+>", " ", without_style)
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()


def _has_meaningful_visual(value: str) -> bool:
    markers = (
        "rendered-chart", "data:image/png", "mermaid-fallback", "<svg", "code-card",
        "shiki-dual-theme", "formula", "<details", "metric-card", "flow-strip",
        "comparison-table", "timeline", "step-grid", "linked-list", "graph-map",
        "graph-node", "node-link-visual", "<table",
    )
    return any(marker in value for marker in markers)


def _has_raw_visual_source(value: str) -> bool:
    return bool(re.search(r"<pre\b[^>]*class=['\"][^'\"]*\bmermaid\b", value)) or ("chart-box" in value and "rendered-chart" not in value)


def _is_tts_script(value: str) -> bool:
    forbidden = ("<", ">", "```", "[pause", "SSML", "<speak", "</speak", "markdown")
    return bool(value.strip()) and not any(marker in value for marker in forbidden)


def _is_detailed_tutor_script(value: str) -> bool:
    text = value.strip()
    markers = sum(marker in text for marker in ("실전", "오답", "약점", "p.", "연습", "판단"))
    return 800 <= len(text) <= 2400 and markers >= 4


def _ngram_repetition_ratio(value: str) -> float:
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", value.lower())
    if len(tokens) < 20:
        return 0.0
    grams = list(zip(tokens, tokens[1:], tokens[2:], strict=False))
    if not grams:
        return 0.0
    return 1.0 - (len(set(grams)) / len(grams))


def _has_tts_delivery_style(value: str) -> bool:
    text = value.strip()
    style_markers = sum(
        marker in text
        for marker in ("자,", "여기서", "한 번", "실전에서는", "오답 함정", "이 약점", "마지막으로", "생각해봅시다")
    )
    endings = sum(text.count(ending) for ending in ("요.", "다.", "죠."))
    raw_acronym_hit = bool(re.search(r"\b(?:FP|FN|F1|ROC|AUC)\b", text))
    pronunciation_hit = any(marker in text for marker in ("에프 피", "에프 엔", "에프 원", "알오씨", "에이유씨", "거짓 양성", "거짓 음성"))
    slash_acronym = bool(re.search(r"\b(?:FP|FN|F1|ROC|AUC)\s*/\s*(?:FP|FN|F1|ROC|AUC)\b", text))
    return style_markers >= 5 and endings >= 8 and (not raw_acronym_hit or pronunciation_hit) and not slash_acronym


def _add_pair(items: list[dict[str, Any]], key: str, label: str, max_score: int, pair: tuple[int, str]) -> None:
    score, note = pair
    _add(items, key, label, max_score, score, note)


def _add(items: list[dict[str, Any]], key: str, label: str, max_score: int, score: int, note: str) -> None:
    items.append({"key": key, "label": label, "max_score": max_score, "score": max(0, min(max_score, score)), "note": note})


def _total(items: list[dict[str, Any]]) -> int:
    max_score = sum(int(item["max_score"]) for item in items)
    raw_score = sum(int(item["score"]) for item in items)
    return round(raw_score * 100 / max_score) if max_score else 0


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
