from __future__ import annotations

import json

from app.modules.ChapterStudio_V1.pipeline.parallel_prompts import parse_slides


def test_parse_slides_renders_visual_spec_to_html() -> None:
    payload = {
        "slides": [
            {
                "slide_idx": 0,
                "title": "영하 수 비교",
                "category": "math",
                "narration": "수직선에서는 오른쪽에 있는 수가 더 큽니다.",
                "visual": {
                    "type": "number_line",
                    "data": {
                        "min": -10,
                        "max": 0,
                        "ticks": [{"value": -10, "label": "영하 10"}, {"value": -5, "label": "영하 5"}, {"value": 0, "label": "0"}],
                        "points": [{"value": -10, "label": "영하 10"}, {"value": -5, "label": "영하 5"}],
                        "highlights": [{"from": -10, "to": -5, "label": "거리 5"}],
                        "arrow": "right_bigger",
                    },
                },
                "checkpoint": "-10과 -5 중 더 큰 수를 말할 수 있는가?",
            }
        ]
    }

    slide = parse_slides(json.dumps(payload, ensure_ascii=False))[0]

    assert slide.html.startswith('<section class="visual-slide">')
    assert "number-line-visual" in slide.html
    assert "영하 10" in slide.html
    assert slide.narration == "수직선에서는 오른쪽에 있는 수가 더 큽니다."
    assert slide.visual["type"] == "number_line"


def test_parse_slides_uses_safe_fallback_when_visual_missing() -> None:
    payload = {
        "slides": [
            {
                "slide_idx": 0,
                "title": "복구 슬라이드",
                "category": "math",
                "narration": "스펙이 비어도 슬라이드는 깨지지 않아야 합니다.",
                "checkpoint": "안전 폴백 확인",
            }
        ]
    }

    slide = parse_slides(json.dumps(payload, ensure_ascii=False))[0]

    assert "example-box-visual" in slide.html
    assert "<svg" in slide.html
    assert slide.visual["type"] == "example_box"
