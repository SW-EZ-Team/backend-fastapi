# postprocess/pipeline.py — postprocess_slide / postprocess_all 단위 테스트다.
# Mock을 사용해 외부 툴 없이 파이프라인 흐름과 반환 구조를 검증하기 위함이다.
import pytest
from unittest.mock import AsyncMock, patch

from app.modules.ChapterStudio_V1.postprocess.pipeline import postprocess_slide, postprocess_all


@pytest.mark.asyncio
class TestPostprocessSlide:
    async def test_returns_required_keys(self):
        result = await postprocess_slide(
            slide_index=0,
            category="text",
            raw_html="<p>hello</p>",
            raw_css="body {}",
        )
        assert "index" in result
        assert "category" in result
        assert "html" in result
        assert "css" in result
        assert "iframe_html" in result
        assert "warnings" in result

    async def test_index_preserved(self):
        result = await postprocess_slide(
            slide_index=5,
            category="text",
            raw_html="<p>x</p>",
            raw_css="",
        )
        assert result["index"] == 5

    async def test_category_preserved(self):
        result = await postprocess_slide(
            slide_index=0,
            category="math",
            raw_html="<p>no math here</p>",
            raw_css="",
        )
        assert result["category"] == "math"

    async def test_css_preserved(self):
        css = ".test { color: blue; }"
        result = await postprocess_slide(
            slide_index=0,
            category="text",
            raw_html="<p>x</p>",
            raw_css=css,
        )
        assert result["css"] == css

    async def test_iframe_css_includes_code_theme_before_raw_css(self):
        css = "pre { background: #2A3B45; color: #fff; }"
        result = await postprocess_slide(
            slide_index=0,
            category="text",
            raw_html='<div class="code-card"><pre class="code-theme"><code><span class="tok-keyword">from</span></code></pre></div>',
            raw_css=css,
        )
        assert "--tok-keyword" in result["iframe_html"]
        assert "prefers-color-scheme:dark" in result["iframe_html"]
        assert result["iframe_html"].find("--tok-keyword") < result["iframe_html"].find("color: #fff")
        assert result["iframe_html"].find("color: #fff") < result["iframe_html"].find("body .metric-card")

    async def test_iframe_css_includes_visual_theme_for_node_links(self):
        result = await postprocess_slide(
            slide_index=0,
            category="interactive",
            raw_html='<details open><summary>연결</summary><ol class="linked-list"><li>head</li><li>node</li></ol></details>',
            raw_css="",
        )
        assert "linked-list" in result["iframe_html"]
        assert "node-link-visual" in result["iframe_html"]

    async def test_flow_strip_model_arrow_children_are_hidden(self):
        result = await postprocess_slide(
            slide_index=0,
            category="diagram",
            raw_html='<section><div class="flow-strip"><div class="step">전처리 오류</div><div class="arrow">→</div><div class="step">모델링 왜곡</div></div></section>',
            raw_css=".arrow{margin:0 10px;font-size:20px}",
        )
        assert "body .flow-strip&gt;.arrow" in result["iframe_html"]
        assert ".flow-strip&gt;.arrow" in result["iframe_html"]

    async def test_flow_strip_unclassed_arrow_only_children_are_marked(self):
        result = await postprocess_slide(
            slide_index=0,
            category="diagram",
            raw_html="<section><div class='flow-strip'><div>전처리</div><div style='font-size:20px;'>→</div><div>해석</div></div></section>",
            raw_css="",
        )
        assert "class=&quot;flow-arrow&quot;" in result["iframe_html"]
        assert "body .flow-strip&gt;.arrow,body .flow-strip&gt;.connector,body .flow-strip&gt;.flow-arrow" in result["iframe_html"]

    async def test_iframe_html_contains_iframe_tag(self):
        result = await postprocess_slide(
            slide_index=0,
            category="text",
            raw_html="<p>hello</p>",
            raw_css="",
        )
        assert "<iframe" in result["iframe_html"]

    async def test_warnings_is_list(self):
        result = await postprocess_slide(
            slide_index=0,
            category="text",
            raw_html="<p>hi</p>",
            raw_css="",
        )
        assert isinstance(result["warnings"], list)

    async def test_shiki_called_only_for_code_category(self):
        with patch("app.modules.ChapterStudio_V1.postprocess.pipeline.shiki_render", new_callable=AsyncMock) as mock_shiki:
            mock_shiki.return_value = ("<p>code</p>", [])
            await postprocess_slide(0, "code", "<p>c</p>", "")
            mock_shiki.assert_called_once()

    async def test_shiki_not_called_for_text_category(self):
        with patch("app.modules.ChapterStudio_V1.postprocess.pipeline.shiki_render", new_callable=AsyncMock) as mock_shiki:
            mock_shiki.return_value = ("<p>text</p>", [])
            await postprocess_slide(0, "text", "<p>t</p>", "")
            mock_shiki.assert_not_called()

    async def test_shiki_runs_for_embedded_code_block(self):
        with patch("app.modules.ChapterStudio_V1.postprocess.pipeline.shiki_render", new_callable=AsyncMock) as mock_shiki:
            mock_shiki.return_value = ("<div class='code-card'>ok</div>", [])
            await postprocess_slide(0, "text", '<pre><code data-lang="python">x = 1</code></pre>', "")
            mock_shiki.assert_called_once()

    async def test_mermaid_called_only_for_diagram_category(self):
        with patch("app.modules.ChapterStudio_V1.postprocess.pipeline.mermaid_render", new_callable=AsyncMock) as mock_m:
            mock_m.return_value = ("<svg/>", [])
            await postprocess_slide(0, "diagram", "<p>d</p>", "")
            mock_m.assert_called_once()

    async def test_mermaid_runs_for_embedded_diagram_block(self):
        with patch("app.modules.ChapterStudio_V1.postprocess.pipeline.mermaid_render", new_callable=AsyncMock) as mock_m:
            mock_m.return_value = ("<svg/>", [])
            await postprocess_slide(0, "text", '<pre class="mermaid">flowchart LR\nA-->B</pre>', "")
            mock_m.assert_called_once()

    async def test_mermaid_runs_for_single_quote_class(self):
        with patch("app.modules.ChapterStudio_V1.postprocess.pipeline.mermaid_render", new_callable=AsyncMock) as mock_m:
            mock_m.return_value = ("<svg/>", [])
            await postprocess_slide(0, "interactive", "<pre class='mermaid'>flowchart LR\nA-->B</pre>", "")
            mock_m.assert_called_once()

    async def test_katex_called_for_math_category(self):
        with patch("app.modules.ChapterStudio_V1.postprocess.pipeline.katex_render", new_callable=AsyncMock) as mock_k:
            mock_k.return_value = ("<p>math</p>", [])
            await postprocess_slide(0, "math", "<p>m</p>", "")
            mock_k.assert_called_once()

    async def test_katex_called_for_math_science_category(self):
        with patch("app.modules.ChapterStudio_V1.postprocess.pipeline.katex_render", new_callable=AsyncMock) as mock_k:
            mock_k.return_value = ("<p>ms</p>", [])
            await postprocess_slide(0, "math-science", "<p>ms</p>", "")
            mock_k.assert_called_once()

    async def test_katex_runs_for_embedded_formula(self):
        with patch("app.modules.ChapterStudio_V1.postprocess.pipeline.katex_render", new_callable=AsyncMock) as mock_k:
            mock_k.return_value = ("<p>formula</p>", [])
            await postprocess_slide(0, "text", r"<p>\[x+1\]</p>", "")
            mock_k.assert_called_once()

    async def test_chart_render_called_for_chart_category(self):
        with patch("app.modules.ChapterStudio_V1.postprocess.pipeline.chart_render", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = ("<img/>", [])
            await postprocess_slide(0, "chart", "<div class='chart-box'/>", "")
            mock_c.assert_called_once()

    async def test_chart_runs_for_embedded_chart_box(self):
        with patch("app.modules.ChapterStudio_V1.postprocess.pipeline.chart_render", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = ("<img/>", [])
            await postprocess_slide(0, "text", '<div class="chart-box" data-chart-type="bar" data-chart-spec="{}"></div>', "")
            mock_c.assert_called_once()

    async def test_quality_gate_replaces_trailing_html_garbage_with_svg_fallback(self):
        result = await postprocess_slide(
            slide_index=0,
            category="text",
            raw_html="<html><body><p>깨진 문서</p></body></html>뒤 쓰레기",
            raw_css="",
        )

        assert "example-box-visual" in result["html"]
        assert "<svg" in result["html"]
        assert any("visual-quality" in warning for warning in result["warnings"])

    async def test_quality_gate_replaces_plain_text_only_body_with_svg_fallback(self):
        result = await postprocess_slide(
            slide_index=1,
            category="text",
            raw_html="<section><p>긴 문단 하나뿐입니다.</p></section>",
            raw_css="",
        )

        assert "example-box-visual" in result["html"]
        assert "<svg" in result["html"]


@pytest.mark.asyncio
class TestPostprocessAll:
    async def test_returns_list(self):
        slides = [
            {"index": 0, "category": "text", "html": "<p>a</p>", "css": ""},
            {"index": 1, "category": "text", "html": "<p>b</p>", "css": ""},
        ]
        results = await postprocess_all(slides)
        assert isinstance(results, list)
        assert len(results) == 2

    async def test_results_sorted_by_index(self):
        slides = [
            {"index": 2, "category": "text", "html": "<p>c</p>", "css": ""},
            {"index": 0, "category": "text", "html": "<p>a</p>", "css": ""},
            {"index": 1, "category": "text", "html": "<p>b</p>", "css": ""},
        ]
        results = await postprocess_all(slides)
        assert [r["index"] for r in results] == [0, 1, 2]

    async def test_empty_slides_returns_empty(self):
        results = await postprocess_all([])
        assert results == []

    async def test_single_slide(self):
        slides = [{"index": 0, "category": "text", "html": "<p>x</p>", "css": ""}]
        results = await postprocess_all(slides)
        assert len(results) == 1
        assert results[0]["index"] == 0
