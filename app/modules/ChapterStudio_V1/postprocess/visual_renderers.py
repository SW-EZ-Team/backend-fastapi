from __future__ import annotations

import re
from collections.abc import Callable

from app.modules.ChapterStudio_V1.postprocess.visual_renderer_utils import (
    axis_x as _x,
    card as _card,
    color as _color,
    coords as _coords,
    items as _items,
    mapping as _mapping,
    narration_text as _narration_text,
    nice as _nice,
    num as _num,
    records as _records,
    step_card as _step_card,
    svg_block as _svg_block,
    text as _text,
)

Spec = dict[str, object]
Renderer = Callable[[Spec], str]
_PLACEHOLDER_PATTERNS = (
    re.compile(r"^시각 자료$"),
    re.compile(r"^슬라이드\s*\d+\s*시각 자료$"),
    re.compile(r"^[\w가-힣 -]*핵심 내용을 예제 카드로 정리한다\.?$"),
    re.compile(r"^핵심 조건을 다시 확인한다\.?$"),
)


def render_number_line(spec: Spec) -> str:
    """수직선 비교를 정적 SVG로 렌더링한다."""
    min_v = _num(spec.get("min"), -10.0)
    max_v = _num(spec.get("max"), 10.0)
    if min_v == max_v:
        max_v = min_v + 1.0
    axis_y = 118.0
    parts = [
        '<line x1="72" y1="118" x2="638" y2="118" stroke="var(--visual-ink,#1F2A30)" stroke-width="3"></line>',
        '<polygon class="number-line-arrow" points="638,118 624,110 624,126" fill="var(--visual-ink,#1F2A30)"></polygon>',
    ]
    for item in _records(spec.get("highlights")):
        x1 = _x(_num(item.get("from"), min_v), min_v, max_v)
        x2 = _x(_num(item.get("to"), max_v), min_v, max_v)
        left, right = sorted((x1, x2))
        label = _text(item.get("label"), "거리")
        parts.append(f'<rect x="{left:.1f}" y="72" width="{right-left:.1f}" height="14" rx="7" fill="var(--visual-accent-soft,#DFF3E7)"></rect>')
        parts.append(f'<line x1="{left:.1f}" y1="79" x2="{right:.1f}" y2="79" stroke="var(--visual-accent,#207B4C)" stroke-width="3"></line>')
        parts.append(f'<text x="{(left+right)/2:.1f}" y="62" text-anchor="middle" font-size="16" fill="var(--visual-accent,#207B4C)">{label}</text>')
    for item in _records(spec.get("ticks")):
        value = _num(item.get("value"), 0.0)
        label = _text(item.get("label"), _nice(value))
        x = _x(value, min_v, max_v)
        parts.append(f'<line x1="{x:.1f}" y1="102" x2="{x:.1f}" y2="134" stroke="var(--visual-muted,#4F6068)" stroke-width="2"></line>')
        parts.append(f'<text x="{x:.1f}" y="158" text-anchor="middle" font-size="15" fill="var(--visual-muted,#4F6068)">{label}</text>')
    for item in _records(spec.get("points")):
        value = _num(item.get("value"), 0.0)
        label = _text(item.get("label"), _nice(value))
        color = _color(item.get("color"), "var(--visual-accent,#207B4C)")
        x = _x(value, min_v, max_v)
        parts.append(f'<circle cx="{x:.1f}" cy="{axis_y:.1f}" r="9" fill="{color}" stroke="var(--visual-paper,#FFFDF7)" stroke-width="4"></circle>')
        parts.append(f'<text x="{x:.1f}" y="42" text-anchor="middle" font-size="17" fill="var(--visual-ink,#1F2A30)">{label}</text>')
    if spec.get("arrow") == "right_bigger":
        parts.append('<text x="568" y="202" text-anchor="middle" font-size="16" fill="var(--visual-accent,#207B4C)">오른쪽으로 갈수록 큼</text>')
    return _svg_block("number-line-visual", "0 0 720 220", "".join(parts))


def render_comparison(spec: Spec) -> str:
    """좌우 비교 카드와 결론을 SVG 강조선과 함께 렌더링한다."""
    left = _mapping(spec.get("left"))
    right = _mapping(spec.get("right"))
    verdict = _text(spec.get("verdict"), "비교 기준을 확인한다.")
    svg = _svg_block(
        "comparison-scale",
        "0 0 720 90",
        '<line x1="140" y1="45" x2="580" y2="45" stroke="var(--visual-line,#C9D5C4)" stroke-width="6"></line>'
        '<circle cx="360" cy="45" r="20" fill="var(--visual-accent,#207B4C)"></circle>'
        '<text x="360" y="51" text-anchor="middle" font-size="16" fill="#FFFFFF">vs</text>',
    )
    return (
        '<div class="comparison-visual">'
        f"{svg}<div class=\"comparison-columns\">{_card(left)}{_card(right)}</div>"
        f'<p class="visual-verdict">{verdict}</p></div>'
    )


def render_step_flow(spec: Spec) -> str:
    """단계 흐름을 번호 배지와 화살표 SVG로 렌더링한다."""
    steps = _records(spec.get("steps")) or [{"label": "시작", "detail": "핵심 조건을 확인한다.", "result": "다음 단계로 이동"}]
    width = 720
    gap = width / max(len(steps), 1)
    nodes: list[str] = []
    cards: list[str] = []
    for idx, step in enumerate(steps[:6]):
        x = gap * idx + gap / 2
        nodes.append(f'<circle cx="{x:.1f}" cy="52" r="22" fill="var(--visual-accent,#207B4C)"></circle>')
        nodes.append(f'<text x="{x:.1f}" y="58" text-anchor="middle" font-size="17" fill="#FFFFFF">{idx + 1}</text>')
        if idx < len(steps[:6]) - 1:
            nodes.append(f'<line x1="{x+28:.1f}" y1="52" x2="{x+gap-28:.1f}" y2="52" stroke="var(--visual-line,#C9D5C4)" stroke-width="4"></line>')
            nodes.append(f'<polygon points="{x+gap-28:.1f},52 {x+gap-42:.1f},44 {x+gap-42:.1f},60" fill="var(--visual-line,#C9D5C4)"></polygon>')
        cards.append(_step_card(idx + 1, step))
    card_html = "".join(cards)
    return f'<div class="step-flow-visual">{_svg_block("step-flow-svg", "0 0 720 105", "".join(nodes))}<div class="step-grid">{card_html}</div></div>'


def render_fraction_bar(spec: Spec) -> str:
    """분수 막대를 분모 칸과 분자 채움으로 렌더링한다."""
    fractions = _records(spec.get("fractions")) or [{"num": 1, "den": 2, "label": "1/2"}]
    rows: list[str] = []
    for item in fractions[:4]:
        den = max(1, int(_num(item.get("den"), 1.0)))
        num = min(max(0, int(_num(item.get("num"), 0.0))), den)
        label = _text(item.get("label"), f"{num}/{den}")
        cells = []
        for idx in range(den):
            fill = "var(--visual-accent,#207B4C)" if idx < num else "var(--visual-paper,#FFFDF7)"
            cells.append(f'<rect x="{90 + idx * 500 / den:.1f}" y="38" width="{500 / den:.1f}" height="46" fill="{fill}" stroke="var(--visual-line,#C9D5C4)" stroke-width="2"></rect>')
        rows.append(_svg_block("fraction-bar-svg", "0 0 720 120", f'<text x="46" y="67" text-anchor="middle" font-size="18" fill="var(--visual-ink,#1F2A30)">{label}</text>{"".join(cells)}'))
    return f'<div class="fraction-bar-visual">{"".join(rows)}</div>'


def render_concept_map(spec: Spec) -> str:
    """노드와 엣지를 개념 관계도 SVG로 렌더링한다."""
    nodes = _records(spec.get("nodes"))[:8] or [{"id": "a", "label": "개념"}, {"id": "b", "label": "예시"}]
    edges = _records(spec.get("edges"))
    coords = _coords(nodes)
    parts: list[str] = []
    for edge in edges:
        start = str(edge.get("from", ""))
        end = str(edge.get("to", ""))
        if start in coords and end in coords:
            x1, y1 = coords[start]
            x2, y2 = coords[end]
            parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="var(--visual-accent-2,#2A5C7A)" stroke-width="3"></line>')
            parts.append(f'<text x="{(x1+x2)/2:.1f}" y="{(y1+y2)/2-8:.1f}" text-anchor="middle" font-size="13" fill="var(--visual-muted,#4F6068)">{_text(edge.get("label"), "")}</text>')
    for node in nodes:
        node_id = str(node.get("id", ""))
        x, y = coords[node_id]
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="48" fill="var(--visual-wash,#F3F7FB)" stroke="var(--visual-accent,#207B4C)" stroke-width="3"></circle>')
        parts.append(f'<text x="{x:.1f}" y="{y+5:.1f}" text-anchor="middle" font-size="15" fill="var(--visual-ink,#1F2A30)">{_text(node.get("label"), node_id)}</text>')
    return _svg_block("concept-map-visual node-link-visual", "0 0 720 310", "".join(parts))


def render_example_box(spec: Spec) -> str:
    """예제와 풀이를 정적 SVG 아이콘이 있는 박스로 렌더링한다."""
    problem = _text(spec.get("problem"), "예제를 확인한다.")
    answer = _text(spec.get("answer"), "핵심 조건을 적용한다.")
    steps = _items(spec.get("steps")) or ["조건을 표시한다.", "계산 또는 비교를 진행한다.", "답을 확인한다."]
    icon = _svg_block("example-box-icon", "0 0 120 120", '<rect x="18" y="18" width="84" height="84" rx="12" fill="var(--visual-accent-soft,#DFF3E7)" stroke="var(--visual-accent,#207B4C)" stroke-width="4"></rect><path d="M36 62 L54 80 L86 42" fill="none" stroke="var(--visual-accent,#207B4C)" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"></path>')
    rows = "".join(f"<li>{_text(step, '')}</li>" for step in steps[:5])
    return f'<div class="example-box-visual">{icon}<div><h3>{problem}</h3><ol>{rows}</ol><p class="visual-answer">{answer}</p></div></div>'


def render_metric_card(spec: Spec) -> str:
    """핵심 수치·기준을 카드형 텍스트 시각화로 렌더링한다."""
    title = _text(spec.get("title"), _text(spec.get("problem"), "학습 포인트"))
    value = _text(spec.get("value"), _first_item_text(spec, "핵심 기준"))
    caption = _text(spec.get("caption"), _text(spec.get("answer"), value))
    return (
        '<article class="metric-card">'
        f"<h3>{title}</h3><strong>{value}</strong><p>{caption}</p>"
        "</article>"
    )


def render_comparison_table(spec: Spec) -> str:
    """comparison-table 패턴을 실제 표 형태로 렌더링한다."""
    left = _mapping(spec.get("left"))
    right = _mapping(spec.get("right"))
    left_title = _text(left.get("title"), "비교 A")
    right_title = _text(right.get("title"), "비교 B")
    rows = _comparison_rows(_items(left.get("items")), _items(right.get("items")))
    body = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in rows)
    verdict = _text(spec.get("verdict"), f"{left_title}와 {right_title}의 차이를 확인한다.")
    return (
        '<table class="comparison-table"><thead><tr>'
        f"<th>{left_title}</th><th>{right_title}</th></tr></thead>"
        f"<tbody>{body}</tbody></table><p class=\"visual-verdict\">{verdict}</p>"
    )


def render_flow_strip(spec: Spec) -> str:
    """flow-strip 패턴을 가로 흐름 카드로 렌더링한다."""
    steps = _records(spec.get("steps")) or [{"label": "확인", "detail": _first_item_text(spec, "핵심을 확인한다.")}]
    cards = []
    for idx, step in enumerate(steps[:5]):
        label = _text(step.get("label"), f"{idx + 1}단계")
        detail = _text(step.get("detail"), _text(step.get("result"), "다음 기준을 확인한다."))
        cards.append(f'<article><b>{label}</b><span>{detail}</span></article>')
    return f'<div class="flow-strip">{"".join(cards)}</div>'


def render_visual(visual_type: str, data: Spec) -> str:
    """visual.type에 맞는 렌더러를 선택한다."""
    renderer = _RENDERERS.get(visual_type, render_example_box)
    return renderer(data)


def render_visual_slide(title: str, narration: str, visual_type: str, data: Spec) -> str:
    """제목·메인 내레이션·시각 렌더 결과를 하나의 body 조각으로 조립한다.

    제목은 짧은 명사구라 라벨용 _text(120자 cap)로 충분하지만, 메인 내레이션은 학습자가
    읽는 완결 문장이므로 _narration_text를 써서 120자 cap에 의한 문장 중간 절단을 막는다.
    """
    return (
        '<section class="visual-slide">'
        f"<header><h2>{_text(title, '시각 설명')}</h2><p>{_narration_text(narration, '핵심을 시각적으로 확인한다.')}</p></header>"
        f"{render_visual(visual_type, data)}</section>"
    )


def render_fallback_visual(title: str = "학습 포인트", narration: str = "") -> str:
    """렌더 실패나 HTML 품질 실패 시 쓸 안전한 SVG 폴백을 만든다."""
    actual_title = _specific_text(title) or _title_from_narration(narration)
    actual_narration = _specific_text(narration) or f"{actual_title}를 실제 예시와 연결해 확인합니다."
    data = {
        "problem": actual_title,
        "steps": _fallback_steps(actual_title, actual_narration),
        "answer": f"{actual_title} 기준을 적용해 스스로 설명합니다.",
    }
    return render_visual_slide(actual_title, actual_narration, "example_box", data)


def _comparison_rows(left: list[str], right: list[str]) -> list[tuple[str, str]]:
    """좌우 항목 길이가 달라도 표 행을 잃지 않게 맞춘다."""
    size = max(len(left), len(right), 1)
    return [
        (
            _text(left[idx], "") if idx < len(left) else "",
            _text(right[idx], "") if idx < len(right) else "",
        )
        for idx in range(size)
    ]


def _first_item_text(spec: Spec, default: str) -> str:
    """items·steps 계열에서 첫 의미 있는 텍스트를 꺼낸다."""
    items = _items(spec.get("items"))
    if items:
        return items[0]
    steps = _records(spec.get("steps"))
    if steps:
        step = steps[0]
        return _text(step.get("detail"), _text(step.get("label"), default))
    return default


def _fallback_steps(title: str, narration: str) -> list[str]:
    """전달된 본문을 예제 박스 단계로 재사용한다."""
    first = _first_sentence(narration)
    second = f"{title}에서 확인한 기준을 한 번 더 적용합니다."
    return [first, second] if first != second else [first]


def _first_sentence(text: str) -> str:
    """긴 본문에서 첫 문장만 단계 카드에 넣는다."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    match = re.match(r"[^.!?。！？]+[.!?。！？]?", cleaned)
    return match.group(0).strip() if match else cleaned


def _title_from_narration(narration: str) -> str:
    """제목이 generic이면 narration 앞부분을 제목 후보로 압축한다."""
    text = _specific_text(narration)
    if not text:
        return "학습 포인트"
    return _first_sentence(text)[:24].strip() or "학습 포인트"


def _specific_text(value: str) -> str:
    """기존 generic fallback 문구를 실제 콘텐츠로 취급하지 않는다."""
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return ""
    return "" if any(pattern.match(text) for pattern in _PLACEHOLDER_PATTERNS) else text


_RENDERERS: dict[str, Renderer] = {
    "number_line": render_number_line,
    "comparison": render_comparison,
    "comparison-table": render_comparison_table,
    "comparison_table": render_comparison_table,
    "step_flow": render_step_flow,
    "flow-strip": render_flow_strip,
    "flow_strip": render_flow_strip,
    "fraction_bar": render_fraction_bar,
    "concept_map": render_concept_map,
    "example_box": render_example_box,
    "example-box": render_example_box,
    "metric-card": render_metric_card,
    "metric_card": render_metric_card,
}

__all__ = [
    "render_comparison",
    "render_concept_map",
    "render_example_box",
    "render_flow_strip",
    "render_fallback_visual",
    "render_fraction_bar",
    "render_metric_card",
    "render_number_line",
    "render_step_flow",
    "render_visual",
    "render_visual_slide",
]
