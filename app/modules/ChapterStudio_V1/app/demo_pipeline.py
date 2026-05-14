from __future__ import annotations

import base64
import html
import json
from functools import cache

from app.modules.ChapterStudio_V1.app.chart_semantics import chart_css_vars, chart_legend_html, learning_chart_spec
from app.modules.ChapterStudio_V1.app.demo_quality import quality_marks, storage_preview
from app.modules.ChapterStudio_V1.app.demo_pedagogy import assignment, lesson_points, note_blocks, voice_scripts
from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput
from app.modules.ChapterStudio_V1.app.demo_types import DemoQuiz, DemoResult, DemoSlide
from app.modules.ChapterStudio_V1.app.frontend_payload import iframe_srcdoc
from app.modules.ChapterStudio_V1.app.study_templates import SlideFrame, select_template
from app.modules.ChapterStudio_V1.app.template_visuals import visual_css
from app.modules.ChapterStudio_V1.app.tutor_blueprints import TutorBlueprint, blueprint_for
from app.modules.ChapterStudio_V1.postprocess.pipeline import SlideInput, postprocess_all
from app.modules.ChapterStudio_V1.postprocess.syntax_theme import code_theme_css


def demo_steps(engine: str = "mock") -> list[str]:
    """HTML 수동 테스트에서 보여줄 주요 pipeline 단계를 반환한다."""
    generator = "Codex CLI 도구 실행" if engine == "codex_cli" else "Mock 생성 도구 실행"
    return ["Agent 입력 분석", "AI 템플릿·도구 선택", generator, "후처리·보안 렌더", "퀴즈·노트·대본 분리", "DB 저장 매핑 조립"]


async def build_demo_result(
    data: DemoGenerationInput, slide_count: int, template: str = "concept_code"
) -> DemoResult:
    """실제 AI 대신 같은 출력 구조를 만드는 수동 테스트용 pipeline이다."""
    selected = select_template(template, data.topic)
    blueprint = blueprint_for(selected.key)
    frames = selected.frames[:slide_count]
    processed = await postprocess_all(_raw_slides(data, selected.key, blueprint, frames))
    slides: list[DemoSlide] = [
        {
            "slide_idx": item["index"],
            "title": f"{data.topic} · {selected.frames[item['index']].role}",
            "focus": _focus(data, selected.frames[item["index"]]),
            "checkpoint": _checkpoint(data, selected.frames[item["index"]]),
            "category": item["category"],
            "template_role": selected.frames[item["index"]].role,
            "iframe_html": iframe_srcdoc(item["iframe_html"]),
        }
        for item in processed
    ]
    quizzes = _quizzes(data.topic, selected.quiz_mix)
    notes = note_blocks(data, selected.note_blocks, blueprint)
    voices = voice_scripts(data, frames, blueprint)
    return {
        "topic": data.topic,
        "template_label": selected.label,
        "quality_marks": quality_marks(selected, blueprint),
        "slides": slides,
        "quizzes": quizzes,
        "note_blocks": notes,
        "assignment": assignment(data, blueprint),
        "voice_scripts": voices,
        "storage_preview": storage_preview(len(slides), len(quizzes), len(notes), len(voices)),
    }


def _raw_slides(
    data: DemoGenerationInput, template: str, blueprint: TutorBlueprint, frames: tuple[SlideFrame, ...]
) -> list[SlideInput]:
    return [_slide(data, template, blueprint, frame) for frame in frames]


def _slide(data: DemoGenerationInput, template: str, blueprint: TutorBlueprint, frame: SlideFrame) -> SlideInput:
    if frame.category == "chart":
        body = _chart_slide(data, frame, blueprint, template)
    else:
        body = {
            "text": _text_slide,
            "diagram": _diagram_slide,
            "interactive": _interactive_slide,
            "code": _code_slide,
            "math": _math_slide,
        }[frame.category](data, frame, blueprint)
    return {"index": frame.slide_idx, "category": frame.category, "html": body, "css": _css(template)}


def _text_slide(data: DemoGenerationInput, frame: SlideFrame, blueprint: TutorBlueprint) -> str:
    topic = _e(data.topic)
    points = lesson_points(data, blueprint)
    return (
        f'<section class="slide"><p class="eyebrow">{_e(frame.role)}</p><h2>{topic}</h2>'
        f'<p class="lead">{_e(data.learning_goal)}</p><ul class="learn-list">'
        f'<li><span class="tag tag-def">왜 이 주제인가</span>{_e(points[0])}</li>'
        f'<li><span class="tag tag-context">기본 관점</span>{_e(points[1])}</li>'
        f'<li><span class="tag tag-warning">빠른 학습</span>{_e(points[2])}</li>'
        f'</ul><div class="callout callout-check"><span class="tag tag-practice">자가점검</span>{_e(blueprint.transfer_question)}</div></section>'
    )


def _diagram_slide(data: DemoGenerationInput, frame: SlideFrame, blueprint: TutorBlueprint) -> str:
    topic = _e(data.topic)
    graph = f"flowchart LR\nA[{topic}] --> B[관점]\nB --> C[작은 사례]\nC --> D[전이 질문]"
    return f'<section class="slide"><p class="eyebrow">{_e(frame.role)}</p><h2>관계로 보는 {topic}</h2><pre class="mermaid">{graph}</pre><p class="hint">{_e(blueprint.mental_model)}</p></section>'


def _interactive_slide(data: DemoGenerationInput, frame: SlideFrame, blueprint: TutorBlueprint) -> str:
    topic = _e(data.topic)
    return (
        f'<section class="slide"><p class="eyebrow">{_e(frame.role)}</p><h2>짧은 실습 활동</h2>'
        f'<details open><summary>{topic}{_josa(data.topic, "을", "를")} 내 말로 판별하기</summary>'
        f"<ol><li>{_e(blueprint.lens)} 관점으로 핵심 용어 2개를 고른다.</li><li>작은 사례에 대입한다.</li><li>{_e(blueprint.pitfall)} 지점을 표시한다.</li></ol>"
        f'</details><p class="hint">{_e(blueprint.transfer_question)} 이 영역은 퀴즈와 별도인 연습이다.</p></section>'
    )


def _code_slide(data: DemoGenerationInput, frame: SlideFrame, blueprint: TutorBlueprint) -> str:
    code = _e(_code_sample(data.topic))
    return (
        f'<section class="slide"><p class="eyebrow">{_e(frame.role)}</p><h2>코드로 재현</h2>'
        f'<pre><code data-lang="python">{code}</code></pre>'
        f'<ul class="learn-list role-list"><li><span class="tag tag-code">from/import</span>외부 도구를 가져온다.</li><li><span class="tag tag-code">class</span>{_e(blueprint.mental_model)}</li><li><span class="tag tag-code">def</span>재사용 가능한 판단 단위다.</li></ul></section>'
    )


def _chart_slide(data: DemoGenerationInput, frame: SlideFrame, blueprint: TutorBlueprint, template: str) -> str:
    spec = learning_chart_spec(data.topic, template, blueprint)
    encoded = base64.b64encode(json.dumps(spec).encode("utf-8")).decode("utf-8")
    legend = chart_legend_html(spec)
    return f'<section class="slide"><p class="eyebrow">{_e(frame.role)}</p><h2>학습 비중</h2><div class="chart-box" data-chart-type="bar" data-chart-spec="{encoded}"></div>{legend}<p class="hint">{_e(blueprint.fast_route)}</p></section>'


def _math_slide(data: DemoGenerationInput, frame: SlideFrame, blueprint: TutorBlueprint) -> str:
    topic = _e(data.topic)
    return f'<section class="slide"><p class="eyebrow">{_e(frame.role)}</p><h2>{topic}의 작은 식</h2><p>{_e(blueprint.mental_model)}</p><div class="formula">\\[score = base + practice - mistake\\]</div><p class="hint">식은 외우기보다 각 기호가 무엇을 줄이고 늘리는지 읽는다.</p></section>'


def _quizzes(topic: str, mix: tuple[str, ...]) -> list[DemoQuiz]:
    return [_quiz(f"{topic} · {kind} 확인 질문", kind, idx) for idx, kind in enumerate(mix[:5])]


def _quiz(question: str, kind: str, idx: int) -> DemoQuiz:
    return {"question": question, "choices": [f"{kind} 기준", "무작위 선택", "설명 생략", "외부 링크"], "answer_idx": 0, "difficulty": ["하", "중", "중", "상", "상"][idx], "explanation": f"{kind} 문항은 슬라이드 활동과 분리된 평가용 산출물이다."}


def _focus(data: DemoGenerationInput, frame: SlideFrame) -> str:
    return f"{frame.role} · {data.depth} 깊이"


def _checkpoint(data: DemoGenerationInput, frame: SlideFrame) -> str:
    required = ", ".join(frame.must_have[:2])
    return f"{data.topic}에서 {required} 항목을 설명할 수 있는가?"


def _code_sample(topic: str) -> str:
    return f"from dataclasses import dataclass\n\n@dataclass\nclass StudyPoint:\n    title: str\n    score: int\n\n\ndef explain(point: StudyPoint) -> str:\n    message = f'{{point.title}}: {{point.score}}점 기준으로 점검'\n    return message\n\ncurrent = StudyPoint('{topic}', 85)\nprint(explain(current))"


def _e(value: str) -> str:
    return html.escape(value, quote=True)


def _josa(value: str, with_batchim: str, without_batchim: str) -> str:
    stripped = value.strip()
    if not stripped:
        return without_batchim
    code = ord(stripped[-1])
    if 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0:
        return with_batchim
    return without_batchim


@cache
def _css(template: str) -> str:
    base = "".join((
        ":root{--paper:#FFFDF7;--ink:#1F2A30;--ink2:#55646C;--line:#DED8CA;--line2:#ECE6D8;--warn:#C2425B;--honey:#7A6518}",
        "body{margin:0;background:var(--paper);color:var(--ink);font-family:'Pretendard Variable',Pretendard,Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}.slide{padding:22px;min-height:260px}.eyebrow{margin:0 0 8px;color:var(--theme-accent);font-size:12px;font-weight:700;letter-spacing:0}",
        "h2{margin:0 0 12px;color:var(--ink);font-size:22px;line-height:1.28;letter-spacing:0}p,.learn-list,ol{font-size:14px;line-height:1.68;color:var(--ink2)}.lead{padding:10px 12px;border:1px solid var(--line2);border-radius:8px;background:var(--theme-concept);font-size:15px;color:var(--ink)}",
        ".learn-list{padding-left:18px}.learn-list li{margin:6px 0}.callout,.hint,details{border:1px solid var(--line);background:var(--theme-practice);border-radius:8px;padding:10px 12px}.callout-check{display:flex;gap:8px;align-items:flex-start}.hint{background:var(--theme-caution)}summary{font-weight:700;color:var(--ink)}",
        ".tag{display:inline-flex;align-items:center;margin-right:8px;padding:2px 7px;border-radius:999px;font-size:11px;font-weight:760;line-height:1.4;white-space:nowrap}.tag-def{background:#E7F3E8;color:#207B4C}.tag-context{background:#F4F0E5;color:#2A3B45}.tag-warning{background:#FDECEF;color:var(--warn)}.tag-practice{background:#FFF3DA;color:var(--honey)}.tag-code{background:#F3F7FB;color:#1664B8}",
        ".mermaid-fallback{display:flex;align-items:stretch;gap:8px;flex-wrap:wrap;background:#FFFDF7;border:1px solid var(--line);border-radius:8px;padding:12px}.mermaid-node{min-width:122px;flex:1 1 122px;border:1px solid var(--line2);border-radius:8px;padding:10px 12px;background:var(--theme-concept)}.mermaid-node strong{display:block;margin-top:4px;color:var(--ink);font-size:13px;line-height:1.45}.node-id{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--theme-accent);color:#FFFDF7;font-size:11px;font-weight:800}.node-1{background:var(--theme-practice)}.node-2{background:#F3F7FB}.node-3{background:var(--theme-caution)}.mermaid-arrow{display:grid;place-items:center;color:var(--theme-accent);font-size:18px;font-weight:800}.formula{background:var(--theme-concept);border:1px solid var(--line2);border-radius:8px;padding:12px}",
        ".rendered-chart{display:block;width:100%;max-width:680px;height:auto;margin:6px auto 0;border:1px solid var(--line2);border-radius:8px;background:#FFFDF7}",
        ".chart-legend{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:10px 0 0;padding:0;list-style:none}.chart-legend li{display:grid;grid-template-columns:auto 1fr;gap:2px 7px;padding:8px;border:1px solid var(--line2);border-radius:8px;background:#FFFDF7}.chart-legend strong{font-size:12px;color:var(--ink)}.chart-legend span:last-child{grid-column:2;font-size:11px;line-height:1.45;color:var(--ink2)}.chart-swatch{width:12px;height:12px;border-radius:3px;margin-top:2px}.swatch-0{background:var(--chart-0)}.swatch-1{background:var(--chart-1)}.swatch-2{background:var(--chart-2)}",
    ))
    return visual_css(template) + chart_css_vars(template) + code_theme_css() + base
