# 템플릿 디자인 강제(visual_quality.enforce_expected_visual) 단위 테스트다.
# plan-first로 배정된 visual_type 구조가 누락된 슬라이드를 결정적 재렌더로 복구하는지 검증한다.
from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.postprocess.pipeline import postprocess_slide
from app.modules.ChapterStudio_V1.postprocess.visual_quality import (
    EXPECTED_VISUAL_MARKERS,
    enforce_expected_visual,
)
from app.modules.ChapterStudio_V1.postprocess.visual_renderers import render_visual_slide


class TestEnforceExpectedVisual:
    def test_passes_when_expected_marker_present(self) -> None:
        html = render_visual_slide("단계 정리", "차근차근 따라갑니다.", "step_flow", {"steps": [{"label": "1단계"}]})

        result, warnings = enforce_expected_visual(html, "step_flow")

        assert result == html
        assert warnings == []

    def test_repairs_when_expected_marker_missing(self) -> None:
        # example_box 구조만 있는 화면에 step_flow가 배정된 경우 — 템플릿 디자인 무시 상황
        html = render_visual_slide("예제", "예제 풀이입니다.", "example_box", {"problem": "문제"})

        result, warnings = enforce_expected_visual(
            html,
            "step_flow",
            title="단계 정리",
            narration="차근차근 따라갑니다.",
            visual_data={"steps": [{"label": "1단계", "detail": "정의 확인"}]},
        )

        assert EXPECTED_VISUAL_MARKERS["step_flow"] in result
        assert any("visual-template" in w for w in warnings)

    def test_alias_normalization(self) -> None:
        html = render_visual_slide("대조", "비교합니다.", "comparison-table", {})

        # 언더스코어 alias로 들어와도 같은 marker로 인정한다
        result, warnings = enforce_expected_visual(html, "comparison_table")

        assert result == html
        assert warnings == []

    def test_skips_when_no_expected_type(self) -> None:
        result, warnings = enforce_expected_visual("<p>아무 슬라이드</p>", "")

        assert result == "<p>아무 슬라이드</p>"
        assert warnings == []

    def test_skips_unknown_type(self) -> None:
        result, warnings = enforce_expected_visual("<p>아무 슬라이드</p>", "hologram")

        assert result == "<p>아무 슬라이드</p>"
        assert warnings == []


@pytest.mark.anyio
async def test_postprocess_slide_enforces_assigned_visual_type() -> None:
    """후처리 전체 경로에서 배정 visual_type 구조가 최종 iframe 본문에 강제된다."""
    result = await postprocess_slide(
        0,
        "text",
        "<h2>수직선 비교</h2><p>마커 없는 본문 슬라이드.</p>",
        "",
        title="수직선 비교",
        narration="-3과 2를 수직선에서 비교합니다.",
        expected_visual_type="number_line",
        visual_data={"min": -5, "max": 5, "points": [{"value": -3, "label": "-3"}]},
    )

    assert EXPECTED_VISUAL_MARKERS["number_line"] in result["html"]
    assert result["iframe_html"].lstrip().startswith("<iframe")
