from __future__ import annotations

import subprocess

import pytest

from app.modules.ChapterStudio_V1.postprocess import katex


@pytest.fixture(autouse=True)
def clear_formula_cache() -> None:
    katex._FORMULA_CACHE.clear()


@pytest.mark.asyncio
async def test_inline_formula_is_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        return "<span class='katex'>x</span>"

    monkeypatch.setattr(katex, "_run_external", fake_run)
    html, warnings = await katex.katex_render(r"<p>\(x+1\)</p>")
    assert "katex" in html
    assert warnings == []


@pytest.mark.asyncio
async def test_block_formula_is_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        return "<span class='katex-display'>x</span>"

    monkeypatch.setattr(katex, "_run_external", fake_run)
    html, warnings = await katex.katex_render(r"<p>\[x+1\]</p>")
    assert "katex-display" in html
    assert warnings == []


@pytest.mark.asyncio
async def test_render_failure_preserves_original(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        raise subprocess.SubprocessError("실패")

    monkeypatch.setattr(katex, "_run_external", fake_run)
    html, warnings = await katex.katex_render(r"<p>\(x+1\)</p>")
    assert r"\(x+1\)" in html
    assert warnings
