from __future__ import annotations

import html

import pytest

from app.modules.ChapterStudio_V1.app.demo_pipeline import build_demo_result
from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput
from app.modules.ChapterStudio_V1.app.frontend_payload import frontend_preview_payload, iframe_srcdoc
from app.modules.ChapterStudio_V1.common.errors import ConversionError


def test_iframe_srcdoc_extracts_sandboxed_srcdoc() -> None:
    source = html.escape("<!DOCTYPE html><html><body><p>본문</p></body></html>", quote=True)
    result = iframe_srcdoc(f'<iframe sandbox="allow-scripts" srcdoc="{source}"></iframe>')
    assert result.startswith("<!DOCTYPE html>")
    assert "본문" in result


def test_iframe_srcdoc_rejects_forbidden_sandbox() -> None:
    source = html.escape("<html></html>", quote=True)
    with pytest.raises(ConversionError):
        iframe_srcdoc(f'<iframe sandbox="allow-scripts allow-same-origin" srcdoc="{source}"></iframe>')


def test_iframe_srcdoc_rejects_nested_iframe_document() -> None:
    with pytest.raises(ConversionError):
        iframe_srcdoc('<!DOCTYPE html><html><body><iframe srcdoc=""></iframe></body></html>')


def test_iframe_srcdoc_wraps_fragment_as_document() -> None:
    result = iframe_srcdoc("<section>본문</section>")
    assert result.startswith("<!DOCTYPE html>")
    assert "<section>본문</section>" in result


@pytest.mark.asyncio
async def test_frontend_preview_payload_matches_srcdoc_contract() -> None:
    result = await build_demo_result(DemoGenerationInput(topic="프론트 끼워넣기"), 5, "auto")
    payload = frontend_preview_payload(result)
    assert payload["generationStatus"] == "ready"
    assert len(payload["slides"]) == 5
    assert payload["slides"][0]["iframeHtml"].lstrip().startswith("<!DOCTYPE html>")
    assert not payload["slides"][0]["iframeHtml"].lstrip().startswith("<iframe")
