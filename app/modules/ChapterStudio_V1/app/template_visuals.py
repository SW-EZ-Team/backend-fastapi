from __future__ import annotations

from app.modules.ChapterStudio_V1.app.template_types import TemplateVisual, TemplateVisualOption

_BASE = TemplateVisual("#207B4C", "#E7F3E8", "#FFF3DA", "#FDECEF", "check", "정의→적용→자가점검")
_TECH = TemplateVisual("#207B4C", "#F3F7FB", "#E7F3E8", "#FFF3DA", "step", "모델→흐름→구현")
_SCIENCE = TemplateVisual("#207B4C", "#E7F3E8", "#FFF3DA", "#FDECEF", "metric", "관찰→원리→검증")
_HUMAN = TemplateVisual("#2A3B45", "#F4F0E5", "#E7F3E8", "#FDECEF", "timeline", "맥락→근거→평가")
_ANALYTIC = TemplateVisual("#2A3B45", "#F3F7FB", "#FFF3DA", "#FDECEF", "metric", "자료→추론→한계")
_PRACTICE = TemplateVisual("#7A6518", "#FFF3DA", "#E7F3E8", "#FDECEF", "step", "기준→연습→오답")
_CREATIVE = TemplateVisual("#2A3B45", "#FDECEF", "#FFF3DA", "#E7F3E8", "quote", "의도→표현→비평")
_VISUAL_FIRST = TemplateVisual("#2A3B45", "#F3F7FB", "#E7F3E8", "#FFF3DA", "metric", "장면→관계→행동")

_GROUPS: dict[str, tuple[str, ...]] = {
    "base": ("foundation_overview", "process_flow", "cause_effect", "compare_practice"),
    "tech": ("concept_code", "algorithm_trace", "system_design", "engineering_design", "electronics_signal"),
    "science": (
        "lab_protocol", "chem_reaction", "bio_system", "clinical_reasoning", "physics_model",
        "astronomy_space", "earth_science", "environment_sustainability", "health_lifestyle",
    ),
    "human": (
        "person_profile", "research_method", "history_timeline", "humanities_argument",
        "law_policy", "sociology_culture", "geography_region", "media_literacy",
    ),
    "analytic": ("data_analysis", "statistics_inference", "economics_model", "math_reasoning"),
    "practice": ("debug_case", "exam_focus", "visual_map", "vocab_memory", "memory_drill", "exam_visual_drill"),
    "visual_first": ("visual_storyboard", "infographic_summary", "code_visual_walkthrough", "reference_navigation"),
    "creative": ("language_pattern", "reading_argument", "business_strategy", "creative_critique", "writing_structure", "psychology_behavior"),
}

_GROUP_VISUALS = {
    "base": _BASE,
    "tech": _TECH,
    "science": _SCIENCE,
    "human": _HUMAN,
    "analytic": _ANALYTIC,
    "practice": _PRACTICE,
    "creative": _CREATIVE,
    "visual_first": _VISUAL_FIRST,
}
_COLOR_NAMES = {
    "#207B4C": "green 제목",
    "#2A3B45": "slate 제목",
    "#7A6518": "honey 강조",
    "#E7F3E8": "sage 배경",
    "#F4F0E5": "sand 배경",
    "#F3F7FB": "soft blue 배경",
    "#FFF3DA": "honey 배경",
    "#FDECEF": "blush 배경",
}


def visual_spec(template: str) -> TemplateVisual:
    """템플릿 key에 맞는 색·목록·구획 계약을 반환한다."""
    return _VISUALS.get(template, _BASE)


def visual_contract(template: str) -> str:
    """생성 프롬프트와 사용자 요약에 넣을 시각 계약 문장이다."""
    visual = visual_spec(template)
    return (
        f"제목/배지는 {visual.title_color}, 개념 패널은 {visual.concept_bg}, "
        f"실습 패널은 {visual.practice_bg}, 주의·오해는 {visual.caution_bg}, "
        f"목록은 {visual.list_style}, 구획은 {visual.section_rule}"
    )


def visual_summary(template: str) -> str:
    """사용자 화면에 노출할 짧은 시각 요약이다."""
    visual = visual_spec(template)
    title = _COLOR_NAMES.get(visual.title_color, visual.title_color)
    concept = _COLOR_NAMES.get(visual.concept_bg, visual.concept_bg)
    practice = _COLOR_NAMES.get(visual.practice_bg, visual.practice_bg)
    caution = _COLOR_NAMES.get(visual.caution_bg, visual.caution_bg)
    return f"시각: {title} · {concept} 개념 · {practice} 실습 · {caution} 주의 · {visual.list_style} 목록"


def visual_options() -> list[TemplateVisualOption]:
    """프론트가 템플릿별 시각 계약을 미리 볼 수 있는 목록이다."""
    return [_visual_option(key, visual) for key, visual in _VISUALS.items()]


def visual_css(template: str) -> str:
    """iframe 안에서 프론트 팔레트를 재현하는 테마 CSS 조각이다."""
    visual = visual_spec(template)
    return (
        f":root{{--theme-accent:{visual.title_color};--theme-concept:{visual.concept_bg};"
        f"--theme-practice:{visual.practice_bg};--theme-caution:{visual.caution_bg};}}"
        f"{_list_css(visual.list_style)}"
    )


def _visual_option(key: str, visual: TemplateVisual) -> TemplateVisualOption:
    return {
        "value": key,
        "title_color": visual.title_color,
        "concept_bg": visual.concept_bg,
        "practice_bg": visual.practice_bg,
        "caution_bg": visual.caution_bg,
        "list_style": visual.list_style,
        "section_rule": visual.section_rule,
    }


def _list_css(style: str) -> str:
    if style == "step":
        return ".learn-list{counter-reset:item;list-style:none;padding-left:0}.learn-list li{counter-increment:item}.learn-list li::before{content:counter(item);display:inline-grid;place-items:center;width:18px;height:18px;margin-right:8px;border-radius:50%;background:var(--theme-accent);color:#FFFDF7;font-size:11px;font-weight:700}"
    if style == "timeline":
        return ".learn-list{list-style:none;border-left:2px solid var(--theme-accent);padding-left:14px}.learn-list li::before{content:'·';color:var(--theme-accent);font-weight:700;margin-right:7px}"
    if style == "metric":
        return ".learn-list li::marker{color:#7A6518}.learn-list li{border-bottom:1px solid #ECE6D8;padding-bottom:4px}"
    if style == "quote":
        return ".learn-list{list-style:none;padding-left:0}.learn-list li{border-left:2px solid var(--theme-accent);padding-left:10px}"
    return ".learn-list li::marker{color:var(--theme-accent)}"


def _build_visuals() -> dict[str, TemplateVisual]:
    visuals: dict[str, TemplateVisual] = {}
    for group, keys in _GROUPS.items():
        for key in keys:
            visuals[key] = _GROUP_VISUALS[group]
    return visuals


_VISUALS = _build_visuals()

__all__ = ["visual_contract", "visual_css", "visual_options", "visual_spec", "visual_summary"]
