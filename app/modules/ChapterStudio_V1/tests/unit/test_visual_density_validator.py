from __future__ import annotations

from app.modules.ChapterStudio_V1.validators.visual_density import visual_density_warnings


def test_long_text_without_visual_marker_warns() -> None:
    html = "<p>" + "긴 설명입니다. " * 80 + "</p>"

    assert visual_density_warnings(html, "text")


def test_long_text_with_tag_marker_passes() -> None:
    html = '<p><span class="tag tag-def">핵심</span>' + "긴 설명입니다. " * 80 + "</p>"

    assert visual_density_warnings(html, "text") == []


def test_code_without_token_color_class_warns() -> None:
    html = '<pre><code data-lang="python">print(1)</code></pre>'

    assert visual_density_warnings(html, "code")


def test_code_card_with_token_color_class_passes() -> None:
    html = '<div class="code-card"><code><span class="tok-keyword">from</span></code></div>'

    assert visual_density_warnings(html, "code") == []


def test_raw_mermaid_block_warns_for_contrast() -> None:
    html = "<pre class='mermaid'>flowchart LR\nA-->B</pre>"

    warnings = visual_density_warnings(html, "interactive")
    assert any("Mermaid 원문" in warning for warning in warnings)


def test_raw_chart_box_warns_for_unrendered_visual() -> None:
    html = "<div class='chart-box' data-chart-type='bar' data-chart-spec='{}'></div>"

    warnings = visual_density_warnings(html, "text")
    assert any("차트 원문" in warning for warning in warnings)


def test_button_only_interactive_warns() -> None:
    html = "<section><button>다음</button><button>이전</button></section>"

    warnings = visual_density_warnings(html, "interactive")

    assert any("버튼만" in warning for warning in warnings)


def test_linked_list_visual_marker_counts_as_visual() -> None:
    html = '<section><ol class="linked-list"><li>head</li><li>null</li></ol></section>'

    assert visual_density_warnings(html, "interactive") == []
