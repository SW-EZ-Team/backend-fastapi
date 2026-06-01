from __future__ import annotations

import re

_VISUAL_PATTERNS = (
    "rendered-chart", "chart-box", "mermaid-fallback", "mermaid-node", "code-card",
    "formula", "<details", "tag-", "<table", "<svg", "metric-card", "flow-strip",
    "comparison-table", "timeline", "step-grid", "linked-list", "graph-map",
    "graph-node", "node-link-visual", "visual-slide", "number-line-visual",
    "comparison-visual", "step-flow-visual", "fraction-bar-visual",
    "concept-map-visual", "example-box-visual",
)


def visual_density_warnings(html: str, category: str) -> list[str]:
    """글만 많은 슬라이드와 색 없는 코드 블록을 후속 재생성 신호로 잡는다."""
    warnings: list[str] = []
    plain_len = len(re.sub(r"<[^>]+>", " ", html).strip())
    visual_count = sum(pattern in html for pattern in _VISUAL_PATTERNS)
    if plain_len > 650 and visual_count == 0:
        warnings.append("visual-density: 긴 텍스트 슬라이드에 시각 단서가 없다.")
    if "chart-box" in html and "rendered-chart" not in html:
        warnings.append("visual-density: 차트 원문 블록이 렌더링되지 않아 시각자료가 완성되지 않았다.")
    if re.search(r"<pre\b[^>]*class=['\"][^'\"]*\bmermaid\b", html):
        warnings.append("contrast: Mermaid 원문 블록이 렌더링되지 않아 저대비 텍스트가 남았다.")
    if category == "code" and "<code" in html and "tok-keyword" not in html:
        warnings.append("visual-density: 코드 블록에 토큰 색상 클래스가 없다.")
    if category == "interactive" and "<button" in html and "<details" not in html and "node-link-visual" not in html:
        warnings.append("interactive: 버튼만 있는 슬라이드는 실제 상호작용으로 보지 않는다.")
    return warnings


__all__ = ["visual_density_warnings"]
