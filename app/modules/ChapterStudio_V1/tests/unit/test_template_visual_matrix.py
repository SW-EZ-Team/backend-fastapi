from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.app.study_templates import get_template, template_keys
from app.modules.ChapterStudio_V1.postprocess.pipeline import postprocess_slide


_CATEGORY_FIXTURES = {
    "text": '<section><div class="metric-card">핵심</div><ul><li>a</li><li>b</li></ul></section>',
    "diagram": '<section><pre class="mermaid">flowchart LR\nA[개념] --> B[사례]</pre></section>',
    "code": '<section><pre><code data-lang="python">from dataclasses import dataclass\nclass A:\n    pass\ndef f():\n    return 1</code></pre></section>',
    "math": '<section><div class="formula">score = base + practice</div></section>',
    "chart": """<section><div class="chart-box" data-chart-type="bar" data-chart-spec='{"data":{"labels":["개념","예시"],"values":[1,2]},"title":"데모"}'></div></section>""",
    "interactive": "<section><details open><summary>실습</summary><ol><li>생각하기</li></ol></details></section>",
}

_CATEGORY_MARKERS = {
    "text": "metric-card",
    "diagram": "mermaid-fallback",
    "code": "tok-keyword",
    "math": "formula",
    "chart": "rendered-chart",
    "interactive": "<details",
}


def test_template_matrix_has_fixture_for_every_frame_category() -> None:
    for key in template_keys():
        for frame in get_template(key).frames:
            assert frame.category in _CATEGORY_FIXTURES, f"{key} slide {frame.slide_idx}: {frame.category}"


@pytest.mark.asyncio
@pytest.mark.parametrize("category", sorted(_CATEGORY_FIXTURES))
async def test_each_template_category_has_rendered_visual_marker(category: str) -> None:
    result = await postprocess_slide(0, category, _CATEGORY_FIXTURES[category], "")

    assert _CATEGORY_MARKERS[category] in result["html"]
    assert result["warnings"] == []
