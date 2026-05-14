from __future__ import annotations

import base64
import json

import pytest

from app.modules.ChapterStudio_V1.app.demo_agent import _compiled_graph
from app.modules.ChapterStudio_V1.app.study_templates import select_template_decision
from app.modules.ChapterStudio_V1.postprocess import katex, mermaid_cli, shiki
from app.modules.ChapterStudio_V1.postprocess.matplotlib_chart import _render_chart_cached


def test_compiled_graph_is_cached() -> None:
    assert _compiled_graph() is _compiled_graph()


def test_template_selector_scores_domain_keywords() -> None:
    code = select_template_decision("FastAPI 의존성 주입")
    person = select_template_decision("통계학자 로널드 피셔")
    stats = select_template_decision("p-value와 신뢰구간")
    assert code.key == "concept_code"
    assert person.key == "person_profile"
    assert stats.key == "statistics_inference"
    assert code.score > 0
    assert person.score > code.score


def test_chart_render_cache_reuses_identical_spec() -> None:
    _render_chart_cached.cache_clear()
    spec = {"data": {"labels": ["관점", "사례"], "values": [1, 2]}, "title": "캐시"}
    raw = base64.b64encode(json.dumps(spec).encode("utf-8")).decode("utf-8")
    first = _render_chart_cached("bar", raw)
    second = _render_chart_cached("bar", raw)
    assert first == second
    assert _render_chart_cached.cache_info().hits == 1


@pytest.mark.asyncio
async def test_shiki_cache_reuses_identical_code(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        calls.append(input_text)
        return "<pre class='shiki'>ok</pre>"

    shiki._HIGHLIGHT_CACHE.clear()
    monkeypatch.setattr(shiki, "_run_external", fake_run)
    raw = '<pre><code data-lang="python">x = 1</code></pre>'
    await shiki.shiki_render(raw)
    await shiki.shiki_render(raw)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_katex_cache_reuses_identical_formula(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_run(cmd: list[str], input_text: str, timeout_sec: float) -> str:
        calls.append(" ".join(cmd))
        return "<span class='katex'>ok</span>"

    katex._FORMULA_CACHE.clear()
    monkeypatch.setattr(katex, "_run_external", fake_run)
    raw = r"<p>\(a+b\)</p>"
    await katex.katex_render(raw)
    await katex.katex_render(raw)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_mermaid_cache_reuses_identical_source(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_run(cmd: list[str], timeout_sec: float) -> str:
        calls.append(" ".join(cmd))
        return ""

    mermaid_cli._MERMAID_CACHE.clear()
    monkeypatch.setattr(mermaid_cli, "_run_external", fake_run)
    raw = '<pre class="mermaid">flowchart LR\nA[시작] --> B[끝]</pre>'
    await mermaid_cli.mermaid_render(raw)
    await mermaid_cli.mermaid_render(raw)
    assert len(calls) == 1
