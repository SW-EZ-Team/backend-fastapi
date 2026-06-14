from __future__ import annotations

import re
from html import unescape

from app.modules.ChapterStudio_V1.app.template_types import VISUAL_TYPE_ALIASES
from app.modules.ChapterStudio_V1.postprocess.title_rules import (
    relabel_chapter_title as _relabel_title,
)
from app.modules.ChapterStudio_V1.postprocess.visual_renderers import (
    render_fallback_visual,
    render_visual_slide,
)

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
_HEADING_RE = re.compile(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
_PLACEHOLDER_PATTERNS = (
    re.compile(r"^시각 자료$"),
    re.compile(r"^슬라이드\s*\d+\s*시각 자료$"),
    re.compile(r"^[\w가-힣 -]*핵심 내용을 예제 카드로 정리한다\.?$"),
    re.compile(r"^핵심 조건을 다시 확인한다\.?$"),
)
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def ensure_visual_body(
    html: str,
    category: str,
    slide_index: int,
    *,
    title: str = "",
    narration: str = "",
    focus: str = "",
    voice_script: str = "",
) -> tuple[str, list[str]]:
    """렌더된 body가 iframe에 넣어도 안전한지 보고, 실패하면 SVG 폴백으로 교체한다."""
    reasons = _quality_failures(html)
    if not reasons:
        return html, []
    fallback_title = _fallback_title(html, title)
    fallback_narration = _fallback_narration(
        html,
        fallback_title,
        narration,
        focus,
        voice_script,
    )
    warning = "visual-quality: " + ", ".join(reasons)
    return render_fallback_visual(fallback_title, fallback_narration), [warning]


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


def _fallback_title(html: str, title: str) -> str:
    """모델의 generic 제목 대신 슬라이드 안의 실제 제목 후보를 고른다."""
    for candidate in (title, _heading_text(html), _compact_sentences(_plain_text(html), 40)):
        specific = _specific_text(candidate)
        if specific:
            return specific
    return "학습 포인트"


def _fallback_narration(
    html: str,
    title: str,
    narration: str,
    focus: str,
    voice_script: str,
) -> str:
    """본문 후보를 실제 설명 우선순위로 압축해 폴백 카드에 넣는다."""
    for candidate in (narration, voice_script, focus, _plain_text(html)):
        specific = _specific_text(candidate)
        if specific:
            return _compact_sentences(specific)
    return f"{title}를 실제 예시와 연결해 확인합니다."


def _heading_text(html: str) -> str:
    """HTML heading 태그에서 첫 실제 제목을 추출한다."""
    for match in _HEADING_RE.finditer(html):
        specific = _specific_text(_plain_text(match.group(1)))
        if specific:
            return specific
    return ""


def _plain_text(html: str) -> str:
    """태그를 제거하고 사람이 읽을 수 있는 텍스트만 남긴다."""
    without_tags = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()


def _compact_sentences(text: str, max_chars: int = 220) -> str:
    """긴 설명에서 폴백 카드에 들어갈 앞쪽 핵심 문장만 남긴다."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    sentences = re.findall(r"[^.!?。！？]+[.!?。！？]?", cleaned)
    compact = " ".join(part.strip() for part in sentences[:2] if part.strip()) or cleaned
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rsplit(" ", 1)[0].strip() or compact[:max_chars].strip()


def _specific_text(value: str) -> str:
    """기존 generic fallback 문구를 실제 콘텐츠 후보에서 제외한다."""
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return ""
    return "" if any(pattern.match(text) for pattern in _PLACEHOLDER_PATTERNS) else text


# 플랜 visual_type → 렌더 결과에 반드시 존재해야 하는 marker class 매핑.
# visual_renderers.py 각 렌더러의 래퍼 class와 1:1 대응한다(드리프트 시 테스트로 잡는다).
EXPECTED_VISUAL_MARKERS: dict[str, str] = {
    "number_line": "number-line-visual",
    "comparison": "comparison-visual",
    "comparison-table": "comparison-table",
    "step_flow": "step-flow-visual",
    "flow-strip": "flow-strip",
    "fraction_bar": "fraction-bar-visual",
    "concept_map": "concept-map-visual",
    "example_box": "example-box-visual",
    "metric-card": "metric-card",
}


def enforce_expected_visual(
    html: str,
    expected_type: str,
    *,
    title: str = "",
    narration: str = "",
    visual_data: dict[str, object] | None = None,
) -> tuple[str, list[str]]:
    """슬라이드가 배정된 템플릿 visual_type 구조를 실제로 담았는지 검증·복구한다.

    plan-first로 확정된 visual_type의 marker class가 최종 HTML에 없으면(템플릿 디자인
    무시) 결정적 렌더러로 같은 타입을 재렌더해 템플릿 구조를 강제한다.
    expected_type이 비었거나 알 수 없는 타입이면 검증을 건너뛴다(보수적 통과).
    """
    if not expected_type:
        return html, []
    normalized = VISUAL_TYPE_ALIASES.get(expected_type, expected_type)
    marker = EXPECTED_VISUAL_MARKERS.get(normalized)
    if marker is None or marker.lower() in html.lower():
        return html, []
    data = visual_data if isinstance(visual_data, dict) else {}
    fallback_title = _fallback_title(html, title)
    fallback_narration = _fallback_narration(html, fallback_title, narration, "", "")
    repaired = render_visual_slide(fallback_title, fallback_narration, normalized, data)
    warning = f"visual-template: 기대 visual_type={normalized} 구조 누락 — 결정적 재렌더 적용"
    return repaired, [warning]


def relabel_chapter_title(title: str, must_have: list[str] | None = None) -> str:
    """챕터명+번호 형태 제목 재라벨 — title_rules의 단일 진실 소스에 위임한다.

    중복 정규식 정의를 제거하기 위해 로직을 title_rules로 통합했다(이전엔 여기와
    parallel_prompts에 별도 정규식이 있었음). postprocess 계층에서 title 재검증이 필요할 때
    쓸 수 있도록 얇은 re-export로 남긴다.
    """
    return _relabel_title(title, must_have)


__all__ = ["EXPECTED_VISUAL_MARKERS", "enforce_expected_visual", "ensure_visual_body", "relabel_chapter_title"]
