from app.modules.ChapterStudio_V1.postprocess.sanitizer import (
    BASE_ALLOWED_ATTRS,
    BASE_ALLOWED_TAGS,
    INTERACTIVE_EXTRA_TAGS,
    sanitize,
)


class TestSanitizerConstants:
    def test_base_allowed_tags_contains_div(self):
        assert "div" in BASE_ALLOWED_TAGS

    def test_base_allowed_tags_contains_svg(self):
        assert "svg" in BASE_ALLOWED_TAGS

    def test_base_allowed_tags_contains_pre(self):
        assert "pre" in BASE_ALLOWED_TAGS

    def test_interactive_extra_tags_contains_interactive_set(self):
        assert {"button", "details", "summary"} <= INTERACTIVE_EXTRA_TAGS
        assert "script" not in INTERACTIVE_EXTRA_TAGS

    def test_base_allowed_attrs_has_wildcard(self):
        assert "*" in BASE_ALLOWED_ATTRS

    def test_base_allowed_attrs_wildcard_has_class(self):
        assert "class" in BASE_ALLOWED_ATTRS["*"]


class TestSanitizeFunction:
    def test_strips_script_tag_for_non_interactive(self):
        html = "<script>alert('xss')</script><p>hello</p>"
        result = sanitize(html, category="general")
        assert "<script>" not in result
        assert "hello" in result

    def test_allows_allowed_tags(self):
        html = "<div><p>content</p></div>"
        result = sanitize(html, category="text")
        assert "<div>" in result
        assert "<p>" in result

    def test_strips_external_href(self):
        html = '<a href="http://evil.com">click</a>'
        result = sanitize(html, category="text")
        assert "http://evil.com" not in result

    def test_preserves_chart_data_image_src(self):
        html = '<img src="data:image/png;base64,AAAA" alt="차트">'
        result = sanitize(html, category="chart")
        assert 'src="data:image/png;base64,AAAA"' in result

    def test_preserves_svg_geometry_attrs(self):
        html = '<svg viewBox="0 0 10 10"><path d="M0 0L10 10" stroke="red"></path><text x="1" y="2">A</text></svg>'
        result = sanitize(html, category="diagram")
        assert 'd="M0 0L10 10"' in result
        assert 'stroke="red"' in result
        assert 'x="1"' in result

    def test_interactive_category_strips_script_tag(self):
        html = "<script>var x = 1;</script><p>visible</p>"
        result = sanitize(html, category="interactive")
        assert "<script>" not in result

    def test_interactive_category_allows_button(self):
        html = "<button>click</button>"
        result = sanitize(html, category="interactive")
        assert "<button>" in result

    def test_interactive_category_preserves_open_details(self):
        html = "<details open><summary>열기</summary><p>내용</p></details>"
        result = sanitize(html, category="interactive")
        assert "<details open" in result

    def test_non_interactive_strips_button(self):
        html = "<button>click</button>"
        result = sanitize(html, category="code")
        assert "<button>" not in result

    def test_strips_iframe_tag(self):
        html = "<iframe src='x'></iframe>"
        result = sanitize(html, category="text")
        assert "<iframe" not in result

    def test_preserves_code_data_lang_attr(self):
        html = '<code data-lang="python">x = 1</code>'
        result = sanitize(html, category="code")
        assert 'data-lang="python"' in result

    def test_preserves_code_token_classes(self):
        html = '<span class="tok-keyword">from</span><span class="tok-variable">score</span>'
        result = sanitize(html, category="code")
        assert 'class="tok-keyword"' in result
        assert 'class="tok-variable"' in result

    def test_strips_comments(self):
        html = "<!-- comment --><p>text</p>"
        result = sanitize(html, category="text")
        assert "<!-- comment -->" not in result

    def test_empty_html_returns_empty(self):
        result = sanitize("", category="text")
        assert result == ""
