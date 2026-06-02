from __future__ import annotations

import asyncio
import re
from typing import NotRequired, TypedDict

from app.modules.ChapterStudio_V1.postprocess.iframe_sandboxer import wrap_iframe
from app.modules.ChapterStudio_V1.postprocess.katex import katex_render
from app.modules.ChapterStudio_V1.postprocess.matplotlib_chart import chart_render
from app.modules.ChapterStudio_V1.postprocess.mermaid_cli import mermaid_render
from app.modules.ChapterStudio_V1.postprocess.nh3_sanitizer import sanitize
from app.modules.ChapterStudio_V1.postprocess.shiki import shiki_render
from app.modules.ChapterStudio_V1.postprocess.syntax_theme import code_theme_css
from app.modules.ChapterStudio_V1.postprocess.visual_theme import accessibility_guard_css, visual_theme_css
from app.modules.ChapterStudio_V1.postprocess.visual_quality import ensure_visual_body
from app.modules.ChapterStudio_V1.validators.visual_density import visual_density_warnings


class SlideInput(TypedDict):
    index: int
    category: str
    html: str
    css: str
    title: NotRequired[str]
    narration: NotRequired[str]
    focus: NotRequired[str]
    voice_script: NotRequired[str]


class PostprocessResult(TypedDict):
    index: int
    category: str
    html: str
    css: str
    iframe_html: str
    warnings: list[str]


async def postprocess_slide(
    slide_index: int,
    category: str,
    raw_html: str,
    raw_css: str,
    *,
    title: str = "",
    narration: str = "",
    focus: str = "",
    voice_script: str = "",
) -> PostprocessResult:
    """슬라이드 원본을 검증 가능한 sandbox iframe 결과로 바꾼다."""
    warnings: list[str] = []
    html = raw_html
    html = await _code_step(category, html, warnings)
    html = await _diagram_step(category, html, warnings)
    html = await _math_step(category, html, warnings)
    html = await _chart_step(category, html, warnings)
    html = _mark_flow_arrow_children(html)
    html = sanitize(html, category=category)
    html, gate_warnings = ensure_visual_body(
        html,
        category,
        slide_index,
        title=title,
        narration=narration,
        focus=focus,
        voice_script=voice_script,
    )
    warnings.extend(gate_warnings)
    warnings.extend(visual_density_warnings(html, category))
    iframe_html = wrap_iframe(html, css=_compose_iframe_css(raw_css))
    return {
        "index": slide_index,
        "category": category,
        "html": html,
        "css": raw_css,
        "iframe_html": iframe_html,
        "warnings": warnings,
    }


async def postprocess_all(
    slides: list[SlideInput], max_concurrency: int = 10
) -> list[PostprocessResult]:
    """슬라이드별 후처리를 병렬 실행하되 결과 순서를 index로 고정한다."""
    semaphore = asyncio.Semaphore(max_concurrency)
    results = await asyncio.gather(*[_bounded(slide, semaphore) for slide in slides])
    return sorted(results, key=lambda result: result["index"])


async def _bounded(slide: SlideInput, semaphore: asyncio.Semaphore) -> PostprocessResult:
    async with semaphore:
        return await postprocess_slide(
            slide["index"],
            slide["category"],
            slide["html"],
            slide["css"],
            title=slide.get("title", ""),
            narration=slide.get("narration", ""),
            focus=slide.get("focus", ""),
            voice_script=slide.get("voice_script", ""),
        )


async def _code_step(category: str, html: str, warnings: list[str]) -> str:
    if category != "code" and "<pre><code" not in html:
        return html
    rendered, step_warnings = await shiki_render(html)
    warnings.extend(step_warnings)
    return rendered


async def _diagram_step(category: str, html: str, warnings: list[str]) -> str:
    if category != "diagram" and not _has_mermaid(html):
        return html
    rendered, step_warnings = await mermaid_render(html)
    warnings.extend(step_warnings)
    return rendered


async def _math_step(category: str, html: str, warnings: list[str]) -> str:
    if category not in {"math", "math-science"} and not _has_math(html):
        return html
    rendered, step_warnings = await katex_render(html)
    warnings.extend(step_warnings)
    return rendered


async def _chart_step(category: str, html: str, warnings: list[str]) -> str:
    if category != "chart" and not _has_chart(html):
        return html
    rendered, step_warnings = await chart_render(html)
    warnings.extend(step_warnings)
    return rendered


def _has_math(html: str) -> bool:
    return "\\(" in html or "\\[" in html


def _has_mermaid(html: str) -> bool:
    return "mermaid" in html and "<pre" in html


def _has_chart(html: str) -> bool:
    return "chart-box" in html and "<div" in html


def _mark_flow_arrow_children(html: str) -> str:
    """모델이 화살표만 담은 div/span을 만들면 flow-strip 카드화에서 제외한다."""

    def replace(match: re.Match[str]) -> str:
        start = match.group("start")
        if " class=" in start or " class='" in start:
            start = re.sub(
                r"""class=(["'])(.*?)\1""",
                lambda class_match: f'class={class_match.group(1)}{class_match.group(2)} flow-arrow{class_match.group(1)}',
                start,
                count=1,
            )
        else:
            start = start[:-1] + ' class="flow-arrow">'
        return f"{start}{match.group('arrow')}{match.group('end')}"

    return re.sub(
        r"(?P<start><(?P<tag>div|span)\b[^>]*>)\s*(?P<arrow>→|➜|➡|⇒|-&gt;|&rarr;)\s*(?P<end></(?P=tag)>)",
        replace,
        html,
    )


def _compose_iframe_css(raw_css: str) -> str:
    """공통 테마, 모델 CSS, 접근성 가드를 고정 순서로 결합한다."""
    return code_theme_css() + visual_theme_css() + raw_css + accessibility_guard_css()
