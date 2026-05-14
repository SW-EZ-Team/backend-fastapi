from __future__ import annotations

from app.modules.ChapterStudio_V1.app.chart_semantics import chart_css_vars, chart_legend_html, learning_chart_spec
from app.modules.ChapterStudio_V1.app.tutor_blueprints import blueprint_for


def test_statistics_chart_uses_semantic_labels_and_colors() -> None:
    spec = learning_chart_spec("p-value와 신뢰구간", "statistics_inference", blueprint_for("statistics_inference"))
    assert spec["data"] == {"labels": ("변수 구조", "추론 근거", "해석 한계"), "values": (34, 38, 28)}
    assert spec["colors"] == ("#2A3B45", "#207B4C", "#C2425B")
    assert "해석 한계" in chart_legend_html(spec)


def test_chart_css_vars_match_legend_swatch_classes() -> None:
    css = chart_css_vars("chem_reaction")
    assert "--chart-0:#207B4C" in css
    assert "--chart-1:#7A6518" in css
    assert "--chart-2:#C2425B" in css
