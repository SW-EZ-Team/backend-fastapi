from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable

import pytest

from app.modules.ChapterStudio_V1.postprocess.visual_renderers import (
    render_comparison,
    render_concept_map,
    render_example_box,
    render_fallback_visual,
    render_fraction_bar,
    render_number_line,
    render_step_flow,
    render_visual,
    render_visual_slide,
)


@pytest.mark.parametrize(
    ("renderer", "spec"),
    [
        (
            render_number_line,
            {
                "min": -10,
                "max": 0,
                "ticks": [{"value": -10, "label": "영하 10"}, {"value": -5, "label": "영하 5"}, {"value": 0, "label": "0"}],
                "points": [{"value": -10, "label": "영하 10", "color": "#207B4C"}, {"value": -5, "label": "영하 5", "color": "#2A5C7A"}],
                "highlights": [{"from": -10, "to": -5, "label": "절댓값 거리 5"}],
                "arrow": "right_bigger",
            },
        ),
        (render_comparison, {"left": {"title": "-10", "items": ["0에서 멀다"]}, "right": {"title": "-5", "items": ["0에 더 가깝다"]}, "verdict": "-5가 더 큽니다."}),
        (render_step_flow, {"steps": [{"label": "상황", "detail": "값을 놓는다.", "result": "위치 확인"}, {"label": "비교", "detail": "오른쪽을 본다.", "result": "큰 수 판단"}]}),
        (render_fraction_bar, {"fractions": [{"num": 2, "den": 3, "label": "2/3"}]}),
        (render_concept_map, {"nodes": [{"id": "a", "label": "정수"}, {"id": "b", "label": "수직선"}], "edges": [{"from": "a", "to": "b", "label": "표현"}]}),
        (render_example_box, {"problem": "예제", "steps": ["조건 확인", "수직선 표시"], "answer": "정답"}),
    ],
)
def test_visual_renderer_outputs_valid_closed_html_with_svg(
    renderer: Callable[[dict[str, object]], str], spec: dict[str, object]
) -> None:
    html = renderer(spec)

    assert "<svg" in html
    assert "</svg>" in html
    assert "<script" not in html.lower()
    ET.fromstring(f"<root>{html}</root>")


def test_number_line_renders_negative_points_and_arrow() -> None:
    html = render_number_line(
        {
            "min": -10,
            "max": 0,
            "ticks": [{"value": -10, "label": "영하 10"}, {"value": -5, "label": "영하 5"}, {"value": 0, "label": "0"}],
            "points": [{"value": -10, "label": "영하 10", "color": "#207B4C"}, {"value": -5, "label": "영하 5", "color": "#2A5C7A"}],
            "highlights": [{"from": -10, "to": -5, "label": "절댓값 거리 5"}],
            "arrow": "right_bigger",
        }
    )

    assert "영하 10" in html
    assert "영하 5" in html
    assert "number-line-arrow" in html
    assert "<circle" in html


def test_visual_slide_wraps_title_narration_and_renderer() -> None:
    html = render_visual_slide("정수 비교", "오른쪽에 있을수록 더 큰 수입니다.", "number_line", {"min": -2, "max": 2})

    assert "정수 비교" in html
    assert "오른쪽에 있을수록" in html
    assert "visual-slide" in html
    assert "number-line-visual" in html


def test_fallback_visual_hides_internal_recovery_message() -> None:
    html = render_fallback_visual("정수 비교", "오른쪽에 있을수록 더 큰 수입니다.")
    internal_card_message = "검증된 시각" + " 카드"
    internal_recovery_word = "복" + "구"

    assert "example-box-visual" in html
    assert internal_card_message not in html
    assert internal_recovery_word not in html


def test_fallback_visual_uses_actual_narration_when_title_is_generic() -> None:
    html = render_fallback_visual("시각 자료", "음수는 수직선에서 오른쪽에 있을수록 더 큽니다.")

    assert "시각 자료" not in html
    assert "음수는 수직선에서 오른쪽에 있을수록 더 큽니다" in html
    assert "핵심 조건을 다시 확인한다" not in html


def test_text_visual_pattern_aliases_render_specific_markup() -> None:
    metric_html = render_visual("metric-card", {"title": "기준", "value": "오른쪽이 큼"})
    flow_html = render_visual("flow-strip", {"steps": [{"label": "확인", "detail": "0 위치를 찾는다."}]})
    table_html = render_visual(
        "comparison-table",
        {
            "left": {"title": "오개념", "items": ["절댓값만 본다"]},
            "right": {"title": "정답", "items": ["수직선 위치를 본다"]},
        },
    )

    assert "metric-card" in metric_html
    assert "flow-strip" in flow_html
    assert "comparison-table" in table_html
