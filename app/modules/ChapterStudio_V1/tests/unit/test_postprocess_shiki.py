from __future__ import annotations

import subprocess

import pytest

from app.modules.ChapterStudio_V1.postprocess import shiki


@pytest.fixture(autouse=True)
def clear_highlight_cache() -> None:
    shiki._HIGHLIGHT_CACHE.clear()


@pytest.mark.asyncio
async def test_unsupported_language_uses_plain_fallback() -> None:
    html, warnings = await shiki.shiki_render('<pre><code data-lang="brain">x</code></pre>')
    assert "<pre><code>x</code></pre>" in html
    assert warnings


@pytest.mark.asyncio
async def test_supported_language_calls_external(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        return "<pre class='shiki'>ok</pre>"

    monkeypatch.setattr(shiki, "_run_external", fake_run)
    html, warnings = await shiki.shiki_render('<pre><code data-lang="python">x=1</code></pre>')
    assert "shiki-dual-theme" in html
    assert warnings == []


@pytest.mark.asyncio
async def test_inline_style_shiki_output_uses_class_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        return '<pre class="shiki"><span style="color:#ff0000">class</span> A</pre>'

    monkeypatch.setattr(shiki, "_run_external", fake_run)
    html, warnings = await shiki.shiki_render('<pre><code data-lang="python">class A: pass</code></pre>')
    assert "code-card" in html
    assert "tok-keyword" in html
    assert "style=" not in html
    assert warnings == []


@pytest.mark.asyncio
async def test_external_failure_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        raise subprocess.SubprocessError("실패")

    monkeypatch.setattr(shiki, "_run_external", fake_run)
    html, warnings = await shiki.shiki_render('<pre><code data-lang="python">from x import y</code></pre>')
    assert "code-theme" in html
    assert "tok-keyword" in html
    assert warnings == []


@pytest.mark.asyncio
async def test_python_fallback_colors_structural_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        raise subprocess.SubprocessError("실패")

    code = "from x import y\n@dataclass\nclass A:\n    def run(self, point: int):\n        value = 'ok'\n        return print(point + 3)"
    monkeypatch.setattr(shiki, "_run_external", fake_run)
    html, warnings = await shiki.shiki_render(f'<pre><code data-lang="python">{code}</code></pre>')
    assert "code-card" in html
    assert "code-legend" in html
    assert "tok-class" in html
    assert "tok-fn" in html
    assert "tok-variable" in html
    assert "tok-param" in html
    assert "tok-builtin" in html
    assert "tok-decorator" in html
    assert "tok-string" in html
    assert "tok-number" in html
    assert warnings == []


@pytest.mark.asyncio
async def test_javascript_fallback_colors_language_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        raise subprocess.SubprocessError("실패")

    code = "const value = await fetch(url)\nconsole.log(value.name)"
    monkeypatch.setattr(shiki, "_run_external", fake_run)
    html, warnings = await shiki.shiki_render(f'<pre><code data-lang="javascript">{code}</code></pre>')
    assert "javascript 구조 읽기" in html
    assert "tok-keyword" in html
    assert "tok-variable" in html
    assert "tok-fn" in html
    assert "tok-property" in html
    assert warnings == []


@pytest.mark.asyncio
async def test_sql_fallback_colors_keywords_and_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        raise subprocess.SubprocessError("실패")

    code = "SELECT COUNT(score) FROM study_point WHERE score > 80"
    monkeypatch.setattr(shiki, "_run_external", fake_run)
    html, warnings = await shiki.shiki_render(f'<pre><code data-lang="sql">{code}</code></pre>')
    assert "sql 구조 읽기" in html
    assert "tok-keyword" in html
    assert "tok-builtin" in html
    assert "tok-number" in html
    assert warnings == []


@pytest.mark.asyncio
async def test_language_class_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        return "<pre class='shiki'>ok</pre>"

    monkeypatch.setattr(shiki, "_run_external", fake_run)
    html, warnings = await shiki.shiki_render('<pre><code class="language-python">class A: pass</code></pre>')
    assert "shiki-dual-theme" in html
    assert warnings == []


@pytest.mark.asyncio
async def test_single_quote_data_lang_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        raise subprocess.SubprocessError("실패")

    monkeypatch.setattr(shiki, "_run_external", fake_run)
    html, warnings = await shiki.shiki_render("<pre><code data-lang='python'>from x import y</code></pre>")
    assert "code-card" in html
    assert "tok-keyword" in html
    assert warnings == []
