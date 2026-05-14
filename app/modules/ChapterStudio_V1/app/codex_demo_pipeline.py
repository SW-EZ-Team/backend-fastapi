from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.ChapterStudio_V1.ai_connectors.codex_cli_connector import CodexCLIConnector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.app.demo_quality import quality_marks, storage_preview
from app.modules.ChapterStudio_V1.app.demo_types import DemoAssignment, DemoNoteBlock, DemoQuiz, DemoResult, DemoVoiceScript
from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput, prompt_context
from app.modules.ChapterStudio_V1.app.frontend_payload import iframe_srcdoc
from app.modules.ChapterStudio_V1.app.reference_books.prompt_blocks import reference_context_prompt
from app.modules.ChapterStudio_V1.app.study_templates import (
    frame_contract,
    select_template,
    study_quality_contract,
    template_contract,
    visual_contract,
)
from app.modules.ChapterStudio_V1.app.tutor_blueprints import blueprint_contract, blueprint_for
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.postprocess.pipeline import SlideInput, postprocess_all

_SCHEMA_PATH = Path(__file__).with_name("codex_demo_result.schema.json")
_SLIDE_COUNT = 5


class CodexSlide(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, le=4)
    title: str = Field(min_length=1, max_length=40)
    focus: str = Field(min_length=1, max_length=140)
    checkpoint: str = Field(min_length=1, max_length=180)
    category: str = Field(pattern="^(text|diagram|code|math|chart|interactive)$")
    html: str = Field(min_length=1, max_length=5600)
    css: str = Field(default="", max_length=1400)


class CodexQuiz(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    question: str = Field(min_length=1, max_length=180)
    choices: list[str] = Field(min_length=4, max_length=4)
    answer_idx: int = Field(ge=0, le=3)
    difficulty: str = Field(pattern="^(상|중|하|hard|medium|easy|기억|이해|적용|함정 교정|실전 판단|오해)$")
    explanation: str = Field(min_length=1, max_length=420)


class CodexNoteBlock(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    heading: str = Field(min_length=1, max_length=30)
    bullets: list[str] = Field(min_length=2, max_length=5)


class CodexAssignment(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    title: str = Field(min_length=1, max_length=50)
    assignment_format: str = Field(min_length=2, max_length=80)
    expected_minutes: int = Field(ge=5, le=90)
    steps: list[str] = Field(min_length=3, max_length=5)
    rubric: list[str] = Field(min_length=3, max_length=5)


class CodexVoiceScript(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, le=4)
    script_text: str = Field(min_length=1, max_length=760)


class CodexDemoPayload(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    slides: list[CodexSlide] = Field(min_length=_SLIDE_COUNT, max_length=_SLIDE_COUNT)
    quizzes: list[CodexQuiz] = Field(min_length=5, max_length=5)
    note_blocks: list[CodexNoteBlock] = Field(min_length=3, max_length=5)
    assignment: CodexAssignment
    voice_scripts: list[CodexVoiceScript] = Field(min_length=_SLIDE_COUNT, max_length=_SLIDE_COUNT)


async def build_codex_demo_result(data: DemoGenerationInput, template: str) -> DemoResult:
    """Codex CLI OAuth 세션으로 5장 테스트 강의 결과를 만든다."""
    selected = select_template(template, data.topic)
    blueprint = blueprint_for(selected.key)
    response = await CodexCLIConnector().generate(_request(data, selected.key))
    payload = _parse_payload(response.text)
    processed = await postprocess_all(_slide_inputs(payload))
    notes = [_note_dict(block) for block in payload.note_blocks]
    voices = [_voice_dict(script) for script in payload.voice_scripts]
    quizzes = [_quiz_dict(quiz) for quiz in payload.quizzes]
    return {
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
            }
            for item in processed
        ],
        "quizzes": quizzes,
        "note_blocks": notes,
        "assignment": _assignment_dict(payload.assignment),
        "voice_scripts": voices,
        "storage_preview": storage_preview(_SLIDE_COUNT, len(quizzes), len(notes), len(voices)),
    }


def _request(data: DemoGenerationInput, template: str) -> ChapterAIRequest:
    return ChapterAIRequest(
        system=_system_prompt(),
        user=_user_prompt(data, template),
        max_tokens=16384,
        temperature=0.1,
        extra={},
    )


def _parse_payload(text: str) -> CodexDemoPayload:
    try:
        return CodexDemoPayload.model_validate_json(_extract_json_object(text))
    except ValidationError as exc:
        raise ConversionError(f"Codex 데모 응답 형식 오류: {exc}") from exc


def _slide_inputs(payload: CodexDemoPayload) -> list[SlideInput]:
    return [
        {"index": slide.slide_idx, "category": slide.category, "html": slide.html, "css": slide.css}
        for slide in sorted(payload.slides, key=lambda item: item.slide_idx)
    ]


def _quiz_dict(quiz: CodexQuiz) -> DemoQuiz:
    return {
        "question": quiz.question,
        "choices": quiz.choices,
        "answer_idx": quiz.answer_idx,
        "difficulty": quiz.difficulty,
        "explanation": quiz.explanation,
    }


def _note_dict(block: CodexNoteBlock) -> DemoNoteBlock:
    return {"heading": block.heading, "bullets": block.bullets}


def _assignment_dict(assignment: CodexAssignment) -> DemoAssignment:
    return {
        "title": assignment.title,
        "assignment_format": assignment.assignment_format,
        "expected_minutes": assignment.expected_minutes,
        "steps": assignment.steps,
        "rubric": assignment.rubric,
    }


def _voice_dict(script: CodexVoiceScript) -> DemoVoiceScript:
    return {"slide_idx": script.slide_idx, "script_text": script.script_text}


def _system_prompt() -> str:
    return (
        "너는 ChapterStudio_V1 과외형 강의 생성기다. 출력은 단일 JSON 객체 한 개뿐이다. "
        "JSON 외 어떤 텍스트도 출력하지 않는다. 사고 과정, 설명, 주석, markdown fence, "
        "<think> 블록, 헤더, 푸터를 전부 금지한다. "
        "최상위 키는 정확히 slides, quizzes, note_blocks, assignment, voice_scripts 다섯 개다. "
        "slides[i] 키는 정확히 slide_idx, title, focus, checkpoint, category, html, css 일곱 개다. "
        "다른 키(role, required, content 등)는 절대 추가하지 않는다. "
        "quizzes[i] 키는 정확히 question, choices, answer_idx, difficulty, explanation 다섯 개다. "
        "note_blocks는 정확히 3~5개이고, note_blocks[i] 키는 정확히 heading, bullets 두 개다. "
        "assignment 키는 정확히 title, assignment_format, expected_minutes, steps, rubric 다섯 개다. "
        "voice_scripts[i] 키는 정확히 slide_idx, script_text 두 개다. "
        "각 슬라이드는 실제 과외처럼 충분한 설명량을 유지한다. "
        "참고도서 발췌가 주어지면 페이지 번호를 지키되, 발췌에 없는 내용을 근거처럼 쓰지 않는다."
    )


def _user_prompt(data: DemoGenerationInput, template: str) -> str:
    reference_block = reference_context_prompt(data.reference_book_context)
    reference_clause = f"{reference_block}\n" if reference_block else ""
    return (
        f"주제: {data.topic}\n"
        f"{prompt_context(data)}\n"
        f"{reference_clause}"
        f"템플릿 계약: {template_contract(template)}\n"
        f"과외 블루프린트: {blueprint_contract(template)}\n"
        f"슬라이드 프레임:\n{frame_contract(template)}\n"
        f"시각 계약: {visual_contract(template)}\n"
        f"학습 품질 계약: {study_quality_contract()}\n"
        "테스트 모드지만 내용은 대충 쓰지 않는다. 외부 URL을 열람하거나 리포지토리를 분석하지 말고, 주제 문자열만 참고한다. "
        "강의 1개 분량으로 5장의 교육용 HTML 슬라이드, 강의 끝 퀴즈 5개, 핵심 노트 3~5블록, 과제, 슬라이드별 음성 대본을 만든다. "
        "설명 첫 블록은 형식적 목차 제목을 쓰지 말고, 주제가 왜 필요한지와 기본 철학·생각 방식·관점으로 시작한다. "
        "각 슬라이드는 h2, 2~3문장 관점 문단, 핵심 설명 4개, 작동 방식 또는 판단 기준 3단계, 작은 예시, 반례·오해, 자가점검 질문을 포함한다. "
        "줄 배치는 긴 덩어리 대신 짧은 문단, 의미 단위 bullet, 단계 번호, 색상 tag로 나누어 읽기 쉽게 만든다. "
        "slides는 slide_idx 0,1,2,3,4를 정확히 한 번씩 포함한다. "
        "html은 section 본문만 넣고 script, 외부 URL, markdown fence는 넣지 않는다. "
        "각 slide html은 적어도 7개 이상의 학습 문장과 2개 이상의 리스트를 포함해 한 화면을 꽉 채울 만큼 설명한다. "
        "기본 화면은 라이트모드로 설계하고, 배경은 순백색보다 #F8F8F6, #FFFDF7, #F3F7FB 같은 부드러운 학습용 색을 우선한다. "
        "코드 색상과 다크모드 대비는 후처리 공통 테마가 제공하므로 slide css에 color-scheme이나 @media를 반복하지 않는다. "
        "텍스트 단락만 길게 늘리지 말고, 각 슬라이드마다 시각 단서가 먼저 보이게 metric-card, flow-strip, comparison-table, figure, timeline, step-grid 중 하나 이상을 포함한다. "
        "시각자료는 장식이 아니라 학습 역할을 가져야 하며, 각 chart/diagram/code/formula/interactive 블록 아래에는 읽는 법을 한 문장으로 붙인다. "
        "데모 쇼케이스는 전체 5장 묶음 기준으로 코드 블록, data-chart-spec 차트, mermaid 관계도, TeX 수식, interactive 활동이 최소 1회씩 보이게 보조 블록을 넣는다. "
        "slide category는 해당 슬라이드의 주역할이며, 아래 고정 시각 슬롯은 주역할을 보강하는 보조 블록으로 넣는다. "
        "시각요소 배치는 고정한다: slide 0 html에는 data-chart-spec 차트를 반드시 넣고, "
        "slide 1 html에는 <pre class=\"mermaid\">flowchart LR...</pre> 관계도를 반드시 넣고, "
        "slide 2 html에는 <pre><code data-lang=\"python\"> 코드와 <div class=\"formula\">score = base + practice - mistake</div> 수식형 설명을 반드시 함께 넣고, "
        "slide 4 html에는 <details open> 실습 활동을 반드시 넣는다. "
        "중요 구분은 span class=\"tag tag-def\", \"tag tag-context\", \"tag tag-warning\", \"tag tag-practice\" 중 하나로 표시한다. "
        "각 slide category는 슬라이드 프레임에 지정된 값을 그대로 따른다. "
        "interactive는 짧은 실습 활동을 넣되 퀴즈라고 부르지 않는다. "
        "code는 <pre><code data-lang=\"python\"> 안에 from, class, def, 변수 1개씩을 포함하고, 코드 아래에 줄별 해석 리스트를 붙인다. "
        "코드 블록은 토큰 색상이 보이는 것을 전제로 작성하고, 코드 자체를 일반 문단이나 단색 pre로 대체하지 않는다. "
        "chart는 <div class=\"chart-box\" data-chart-type=\"bar\" data-chart-spec='{\"data\":{\"labels\":[\"개념\",\"예시\",\"실습\"],\"values\":[35,30,35]},\"title\":\"학습 비중\",\"colors\":[\"#2A3B45\",\"#207B4C\",\"#7A6518\"]}'></div>처럼 raw JSON을 작은따옴표 속성으로 넣는다. "
        "diagram은 <pre class=\"mermaid\">flowchart LR...</pre>, math/formula는 <div class=\"formula\">score = base + practice - mistake</div> 형식으로 넣고 읽는 법을 설명한다. "
        "css는 Pretendard/Inter 계열 폰트와 시각 계약 색상을 쓰되, 슬라이드 고유 레이아웃만 900자 이하로 쓴다. "
        "quizzes는 슬라이드 실습과 별도인 평가 문항이다. "
        "각 quiz explanation은 정답 근거와 대표 오답이 왜 틀렸는지 함께 설명한다. "
        "note_blocks의 bullet은 한 문장 요약이 아니라 복습 때 바로 떠올릴 수 있는 2문장 설명으로 쓴다. "
        "assignment.assignment_format은 제출 형태를 명확히 쓰며, 예: '서술형 복습지', '표 채우기', '문제풀이+근거 표시', '짧은 프로젝트 체크리스트' 중 주제에 맞게 고른다. "
        "assignment.expected_minutes는 10~30 사이 정수로 쓰고, steps와 rubric은 그 형식에 맞아야 한다. "
        "voice_scripts는 슬라이드마다 5~7문장의 친절한 튜터 말투로, 배경과 핵심 전환점을 자연스럽게 이어준다. "
        "voice_scripts의 각 script_text는 정확히 5~7문장으로 쓰고, 참고도서 발췌가 있으면 각 대본에 p.번호를 최소 1회 자연스럽게 넣는다. "
        "참고도서 발췌가 제공된 경우 암기노트와 음성대본에 p.번호를 자연스럽게 연결하고, "
        "note_blocks의 각 블록은 최소 2개 bullet에 p.번호를 넣어 책 위치와 복습 포인트를 직접 연결한다. "
        "note_blocks 전체에는 서로 다른 bullet에 p.번호를 최소 4회, assignment steps에는 p.번호를 최소 2회 연결한다. "
        "책 설명과 실전 관점의 차이를 풀어쓴다."
    )


def _extract_json_object(text: str) -> str:
    stripped = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    stripped = re.sub(r"<think>.*", "", stripped, flags=re.DOTALL)
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
                return stripped[start : index + 1]
    return stripped[start:]
