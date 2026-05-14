from __future__ import annotations

import html

from app.modules.ChapterStudio_V1.app.template_visuals import visual_spec
from app.modules.ChapterStudio_V1.app.tutor_blueprints import TutorBlueprint

_LABELS: dict[str, tuple[str, str, str]] = {
    "statistics_inference": ("변수 구조", "추론 근거", "해석 한계"),
    "data_analysis": ("변수", "패턴", "주의점"),
    "concept_code": ("입력·상태", "실행 흐름", "검증"),
    "chem_reaction": ("반응 조건", "보존 관계", "오해 지점"),
    "language_pattern": ("형태", "맥락", "오류 수정"),
    "person_profile": ("시대 맥락", "핵심 선택", "영향"),
    "exam_focus": ("출제 언어", "판별 기준", "오답 루틴"),
}
_VALUES: dict[str, tuple[int, int, int]] = {
    "statistics_inference": (34, 38, 28),
    "concept_code": (32, 36, 32),
    "chem_reaction": (30, 40, 30),
    "language_pattern": (35, 35, 30),
    "person_profile": (34, 31, 35),
    "exam_focus": (30, 34, 36),
}
_FALLBACK_LABELS = ("핵심 관점", "작은 사례", "자가점검")
_FALLBACK_VALUES = (35, 30, 35)


def learning_chart_spec(topic: str, template: str, blueprint: TutorBlueprint) -> dict[str, object]:
    """주제·템플릿별 의미가 보이는 차트 spec을 만든다."""
    labels = _LABELS.get(template, _FALLBACK_LABELS)
    values = _VALUES.get(template, _FALLBACK_VALUES)
    return {
        "data": {"labels": labels, "values": values},
        "colors": _colors(template),
        "title": f"{topic} 핵심 분류",
        "x_label": "학습 분류",
        "y_label": "중요도",
        "legend": _legend(labels, blueprint),
    }


def chart_css_vars(template: str) -> str:
    """차트 막대와 범례가 같은 의미 색을 쓰게 CSS 변수를 만든다."""
    colors = _colors(template)
    return f":root{{--chart-0:{colors[0]};--chart-1:{colors[1]};--chart-2:{colors[2]};}}"


def chart_legend_html(spec: dict[str, object]) -> str:
    """차트의 색 의미를 사용자가 바로 읽을 수 있게 범례 HTML을 만든다."""
    data = spec.get("data")
    if not isinstance(data, dict):
        return ""
    labels = _strings(data.get("labels"))
    notes = _strings(spec.get("legend"))
    items = [_legend_item(idx, label, notes) for idx, label in enumerate(labels[:3])]
    return f'<ul class="chart-legend">{"".join(items)}</ul>'


def _colors(template: str) -> tuple[str, str, str]:
    visual = visual_spec(template)
    if template in {"statistics_inference", "data_analysis"}:
        return ("#2A3B45", "#207B4C", "#C2425B")
    if template in {"chem_reaction", "bio_system", "physics_model"}:
        return ("#207B4C", "#7A6518", "#C2425B")
    return (visual.title_color, "#36B36F", "#C2425B")


def _strings(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


def _legend_item(idx: int, label: str, notes: list[str]) -> str:
    note = notes[idx] if idx < len(notes) else label
    return (
        f'<li><span class="chart-swatch swatch-{idx}"></span>'
        f'<strong>{html.escape(label)}</strong><span>{html.escape(note)}</span></li>'
    )


def _legend(labels: tuple[str, str, str], blueprint: TutorBlueprint) -> list[str]:
    return [
        f"{labels[0]}: {blueprint.lens}",
        f"{labels[1]}: {blueprint.fast_route}",
        f"{labels[2]}: {blueprint.pitfall}",
    ]
