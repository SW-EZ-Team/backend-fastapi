from __future__ import annotations

import base64
import json

import pytest

from app.modules.ChapterStudio_V1.postprocess.matplotlib_chart import chart_render
from app.modules.ChapterStudio_V1.postprocess.pipeline import postprocess_slide


def _box(chart_type: str) -> str:
    spec = {"data": {"labels": ["a", "b"], "values": [1, 2]}, "title": "t"}
    raw = base64.b64encode(json.dumps(spec).encode("utf-8")).decode("utf-8")
    return f'<div class="chart-box" data-chart-type="{chart_type}" data-chart-spec="{raw}"></div>'


@pytest.mark.asyncio
@pytest.mark.parametrize("chart_type", ["bar", "line", "scatter", "pie", "histogram"])
async def test_chart_types_return_png_data_uri(chart_type: str) -> None:
    html, warnings = await chart_render(_box(chart_type))
    assert "data:image/png;base64," in html
    assert warnings == []


@pytest.mark.asyncio
async def test_bad_spec_returns_fallback() -> None:
    raw = '<div class="chart-box" data-chart-type="bar" data-chart-spec="not-json"></div>'
    html, warnings = await chart_render(raw)
    assert raw in html
    assert warnings


@pytest.mark.asyncio
async def test_raw_json_spec_in_single_quote_attr_returns_png() -> None:
    raw = """<div class="chart-box" data-chart-type="bar" data-chart-spec='{"data":{"labels":["개념","예시"],"values":[3,2]},"title":"데모"}'></div>"""
    html, warnings = await chart_render(raw)
    assert "data:image/png;base64," in html
    assert warnings == []


@pytest.mark.asyncio
async def test_single_quote_chart_class_in_pipeline_returns_png() -> None:
    raw = """<div class='chart-box' data-chart-type='bar' data-chart-spec='{"data":{"labels":["개념","예시"],"values":[3,2]},"title":"데모"}'></div>"""
    result = await postprocess_slide(0, "text", raw, "")
    assert "data:image/png;base64," in result["html"]
    assert "chart-box" not in result["html"]
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_string_label_expands_to_match_values() -> None:
    spec = {"data": {"labels": "분포 형태", "values": [1, 2, 3]}, "title": "데모"}
    raw = base64.b64encode(json.dumps(spec).encode("utf-8")).decode("utf-8")
    html, warnings = await chart_render(f'<div class="chart-box" data-chart-type="bar" data-chart-spec="{raw}"></div>')
    assert "data:image/png;base64," in html
    assert warnings == []


@pytest.mark.asyncio
async def test_line_chart_accepts_xy_spec_without_values_key() -> None:
    spec = {"data": {"x": [0, 0.5, 1.0], "y": [0, 0.8, 1.0]}, "title": "ROC"}
    raw = base64.b64encode(json.dumps(spec).encode("utf-8")).decode("utf-8")
    html, warnings = await chart_render(f'<div class="chart-box" data-chart-type="line" data-chart-spec="{raw}"></div>')
    assert "data:image/png;base64," in html
    assert warnings == []


@pytest.mark.asyncio
async def test_chart_pipeline_preserves_data_uri_after_sanitize() -> None:
    result = await postprocess_slide(0, "chart", _box("bar"), "")
    assert "data:image/png;base64," in result["html"]
    assert "src=" in result["html"]
