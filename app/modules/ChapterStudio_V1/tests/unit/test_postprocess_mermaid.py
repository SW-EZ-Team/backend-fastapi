from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.ChapterStudio_V1.postprocess import mermaid_cli


@pytest.fixture(autouse=True)
def clear_mermaid_cache() -> None:
    mermaid_cli._MERMAID_CACHE.clear()


@pytest.mark.asyncio
async def test_mermaid_success_returns_svg(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], timeout_sec: float) -> str:
        Path(cmd[-1]).write_text("<svg></svg>", encoding="utf-8")
        return ""

    monkeypatch.setattr(mermaid_cli, "_run_external", fake_run)
    html, warnings = await mermaid_cli.mermaid_render('<pre class="mermaid">graph TD; A-->B</pre>')
    assert "<svg>" in html
    assert warnings == []


@pytest.mark.asyncio
async def test_mermaid_timeout_returns_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], timeout_sec: float) -> str:
        raise TimeoutError("느림")

    monkeypatch.setattr(mermaid_cli, "_run_external", fake_run)
    html, warnings = await mermaid_cli.mermaid_render('<pre class="mermaid">bad</pre>')
    assert "mermaid-fallback" in html
    assert warnings == []


@pytest.mark.asyncio
async def test_mermaid_fallback_builds_colored_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], timeout_sec: float) -> str:
        raise TimeoutError("느림")

    source = "flowchart LR\nA[통계학자] --> B[핵심 개념]\nB --> C[검증 질문]"
    monkeypatch.setattr(mermaid_cli, "_run_external", fake_run)
    html, warnings = await mermaid_cli.mermaid_render(f'<pre class="mermaid">{source}</pre>')
    assert "mermaid-node" in html
    assert "node-id" in html
    assert "flowchart LR" not in html
    assert warnings == []


@pytest.mark.asyncio
async def test_single_quote_mermaid_with_edge_labels_renders_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], timeout_sec: float) -> str:
        raise TimeoutError("느림")

    source = "flowchart LR\nA[전체 데이터] --> B{데이터 분할}\nB -->|70-80%| C[훈련 데이터]"
    monkeypatch.setattr(mermaid_cli, "_run_external", fake_run)
    html, warnings = await mermaid_cli.mermaid_render(f"<pre class='mermaid'>{source}</pre>")
    assert "mermaid-fallback" in html
    assert "전체 데이터" in html
    assert "데이터 분할" in html
    assert "훈련 데이터" in html
    assert "flowchart LR" not in html
    assert warnings == []


@pytest.mark.asyncio
async def test_mermaid_temp_files_are_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def fake_run(cmd: list[str], timeout_sec: float) -> str:
        seen.extend(cmd)
        Path(cmd[-1]).write_text("<svg></svg>", encoding="utf-8")
        return ""

    monkeypatch.setattr(mermaid_cli, "_run_external", fake_run)
    await mermaid_cli.mermaid_render('<pre class="mermaid">graph TD; A-->B</pre>')
    tmp_paths = [Path(item) for item in seen if item.startswith("/tmp/chapterstudio-mmd-")]
    assert tmp_paths
    assert all(not path.exists() for path in tmp_paths)
