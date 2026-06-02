"""음성대본 타깃에 넣을 슬라이드별 화면 힌트 추출."""
from __future__ import annotations

from html.parser import HTMLParser

from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState


def draft_by_idx(state: ChapterStudioState) -> dict[int, dict[str, object]]:
    """생성된 슬라이드 초안을 slide_idx 기준으로 정렬한다."""
    result: dict[int, dict[str, object]] = {}
    for key in ("slide_drafts", "slides"):
        value = state.get(key)
        if not isinstance(value, list):
            continue
        _collect_drafts(value, result)
    return result


def voice_summary(draft: dict[str, object], row: dict[str, object], category: str, role: str) -> str:
    """HTML 화면 텍스트를 우선하고, 없으면 outline의 구체 필드를 요약한다."""
    html_text = _html_hint(draft)
    if html_text:
        return f"category={category}, 화면내용={html_text}"
    outline = _outline_hint(row)
    if outline:
        return f"category={category}, outline={outline}"
    return f"category={category}, 역할={role}"


def previous_title(
    idx: int,
    drafts: dict[int, dict[str, object]],
    outlines: dict[int, dict[str, object]],
) -> str:
    """직전 슬라이드 제목을 병렬 voice 프롬프트 연결 단서로 만든다."""
    if idx <= 0:
        return ""
    draft = drafts.get(idx - 1, {})
    outline = outlines.get(idx - 1, {})
    return first_text(draft.get("title"), outline.get("title"), outline.get("role"))


def first_text(*values: object) -> str:
    """여러 후보 중 첫 번째 비어 있지 않은 문자열을 고른다."""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _collect_drafts(value: list[object], result: dict[int, dict[str, object]]) -> None:
    for row in value:
        if isinstance(row, dict) and isinstance(row.get("slide_idx"), int):
            result[row["slide_idx"]] = row


def _html_hint(draft: dict[str, object]) -> str:
    html = first_text(draft.get("html"), draft.get("html_content"))
    return _limit_text(_strip_html(html), 200)


def _outline_hint(row: dict[str, object]) -> str:
    parts = [first_text(row.get(key)) for key in ("title", "focus", "summary", "description", "narration", "role")]
    must_have = row.get("must_have")
    if isinstance(must_have, list):
        parts.extend(str(item) for item in must_have)
    return _limit_text(" / ".join(part for part in parts if part), 200)


def _strip_html(html: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(html)
    return _limit_text(" ".join(parser.parts), 400)


def _limit_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    return normalized[:limit]


class _HtmlTextExtractor(HTMLParser):
    """HTML 태그 내부 텍스트만 모아 화면 힌트로 쓰기 위한 작은 파서."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


__all__ = ["draft_by_idx", "first_text", "previous_title", "voice_summary"]
