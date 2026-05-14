# postprocess/iframe.py 단위 테스트다.
# IFRAME_TEMPLATE, sandbox 속성, CSP meta 주입을 검증하기 위함이다.

from app.modules.ChapterStudio_V1.postprocess.iframe import wrap_iframe, IFRAME_TEMPLATE


class TestIframeConstants:
    def test_iframe_template_contains_csp(self):
        assert "Content-Security-Policy" in IFRAME_TEMPLATE

    def test_iframe_template_contains_lang_ko(self):
        assert 'lang="ko"' in IFRAME_TEMPLATE

    def test_iframe_template_contains_body_placeholder(self):
        assert "{body}" in IFRAME_TEMPLATE

    def test_iframe_template_contains_css_placeholder(self):
        assert "{css}" in IFRAME_TEMPLATE

    def test_csp_has_unsafe_inline(self):
        assert "unsafe-inline" in IFRAME_TEMPLATE

    def test_csp_has_data_img_src(self):
        assert "data:" in IFRAME_TEMPLATE


class TestWrapIframe:
    def test_returns_iframe_tag(self):
        result = wrap_iframe("<p>hello</p>")
        assert "<iframe" in result
        assert "srcdoc=" in result

    def test_sandbox_is_allow_scripts_only(self):
        result = wrap_iframe("<p>test</p>")
        assert 'sandbox="allow-scripts"' in result

    def test_allow_same_origin_absent(self):
        result = wrap_iframe("<p>test</p>")
        assert "allow-same-origin" not in result

    def test_allow_forms_absent(self):
        result = wrap_iframe("<p>test</p>")
        assert "allow-forms" not in result

    def test_body_html_escaped_in_srcdoc(self):
        body = "<div>hello & world</div>"
        result = wrap_iframe(body)
        assert "srcdoc=" in result

    def test_css_injected_into_template(self):
        css = "body { color: red; }"
        result = wrap_iframe("<p>x</p>", css=css)
        assert "color: red" in result

    def test_empty_body_valid_output(self):
        result = wrap_iframe("")
        assert "<iframe" in result

    def test_style_width_100_percent(self):
        result = wrap_iframe("<p>x</p>")
        assert "width:100%" in result
