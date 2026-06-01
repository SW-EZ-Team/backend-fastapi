from __future__ import annotations

import re

from app.modules.ChapterStudio_V1.postprocess.visual_renderers import render_fallback_visual

_VISUAL_MARKERS = (
    "<svg",
    "<img",
    "<table",
    "<details",
    "visual-slide",
    "mermaid-fallback",
    "mermaid-node",
    "metric-card",
    "flow-strip",
    "comparison-table",
    "rendered-chart",
    "chart-box",
    "formula",
    "katex",
    "code-card",
    "step-grid",
    "linked-list",
    "graph-map",
    "node-link-visual",
    "number-line-visual",
    "comparison-visual",
    "step-flow-visual",
    "fraction-bar-visual",
    "concept-map-visual",
    "example-box-visual",
)
_TAG_RE = re.compile(r"<\s*(/)?\s*([a-zA-Z][\w:-]*)\b[^>]*?>")
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def ensure_visual_body(html: str, category: str, slide_index: int) -> tuple[str, list[str]]:
    """렌더된 body가 iframe에 넣어도 안전한지 보고, 실패하면 SVG 폴백으로 교체한다."""
    reasons = _quality_failures(html)
    if not reasons:
        return html, []
    title = f"슬라이드 {slide_index + 1} 시각 자료"
    narration = _fallback_narration(category, reasons)
    warning = "visual-quality: " + ", ".join(reasons)
    return render_fallback_visual(title, narration), [warning]


def _quality_failures(html: str) -> list[str]:
    failures: list[str] = []
    lower = html.lower()
    if "<script" in lower:
        failures.append("script 태그 제거 필요")
    if "<html" in lower or "<!doctype" in lower:
        failures.append("body 조각이 아닌 전체 HTML 문서 감지")
    if _has_trailing_html_garbage(lower):
        failures.append("</html> 뒤 잔여문자 감지")
    if not _tags_balanced(html):
        failures.append("태그 균형 실패")
    if not _has_visual_marker(lower):
        failures.append("시각요소 없음")
    return failures


def _has_trailing_html_garbage(lower_html: str) -> bool:
    match = re.search(r"</html\s*>", lower_html)
    if match is None:
        return False
    return lower_html[match.end():].strip() != ""


def _has_visual_marker(lower_html: str) -> bool:
    return any(marker.lower() in lower_html for marker in _VISUAL_MARKERS)


def _tags_balanced(html: str) -> bool:
    stack: list[str] = []
    for match in _TAG_RE.finditer(html):
        whole = match.group(0)
        tag = match.group(2).lower()
        if tag.startswith("!") or tag in _VOID_TAGS:
            continue
        if whole.rstrip().endswith("/>"):
            continue
        if match.group(1):
            if not stack or stack[-1] != tag:
                return False
            stack.pop()
        else:
            stack.append(tag)
    return not stack


def _fallback_narration(category: str, reasons: list[str]) -> str:
    return f"{category} 핵심 내용을 예제 카드로 정리한다."


__all__ = ["ensure_visual_body"]
