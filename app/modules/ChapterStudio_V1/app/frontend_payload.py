from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from typing import Literal, TypedDict

from app.modules.ChapterStudio_V1.app.demo_types import DemoResult
from app.modules.ChapterStudio_V1.common.errors import ConversionError

_SANDBOX = "allow-scripts"
_FORBIDDEN_TOKENS = (
    "allow-same-origin", "allow-top-navigation", "allow-forms",
    "allow-popups", "allow-modals",
)
ValidationStatus = Literal["passed", "pending", "failed"]


class LessonSlidePayload(TypedDict):
    slideId: str
    slideIdx: int
    title: str
    category: str
    templateId: str
    iframeHtml: str
    validationStatus: ValidationStatus


class FrontendPreviewPayload(TypedDict):
    tutoringId: str
    lessonId: str
    lessonTitle: str
    generationStatus: str
    slides: list[LessonSlidePayload]


class _IframeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.srcdoc: str | None = None
        self.sandbox: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "iframe" or self.srcdoc is not None:
            return
        values = {key: value for key, value in attrs}
        self.srcdoc = values.get("srcdoc")
        self.sandbox = values.get("sandbox")


def iframe_srcdoc(markup: str) -> str:
    """프론트 빈 iframe의 srcDoc에 넣을 문서 HTML만 반환한다."""
    stripped = markup.strip()
    if _is_document(stripped):
        return _validated_srcdoc(stripped)
    parser = _IframeParser()
    parser.feed(stripped)
    if parser.srcdoc is None:
        return _document(stripped)
    if parser.sandbox != _SANDBOX:
        raise ConversionError("iframe sandbox는 allow-scripts만 허용한다.")
    return _validated_srcdoc(unescape(parser.srcdoc))


def frontend_preview_payload(result: DemoResult) -> FrontendPreviewPayload:
    """데모 결과를 frontend-web의 LessonSlidesDto 계약으로 변환한다."""
    slides: list[LessonSlidePayload] = []
    for slide in result["slides"]:
        slides.append({
            "slideId": f"demo-slide-{slide['slide_idx']:03d}",
            "slideIdx": slide["slide_idx"],
            "title": slide["title"],
            "category": slide["category"],
            "templateId": slide["template_role"],
            "iframeHtml": iframe_srcdoc(slide["iframe_html"]),
            "validationStatus": "passed",
        })
    return {
        "tutoringId": "demo-tutoring",
        "lessonId": "demo-lesson",
        "lessonTitle": result["topic"],
        "generationStatus": "ready",
        "slides": slides,
    }


def _is_document(value: str) -> bool:
    lower = value[:64].lower()
    return lower.startswith("<!doctype html") or lower.startswith("<html")


def _document(body: str) -> str:
    return f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"></head><body>{body}</body></html>'


def _validated_srcdoc(value: str) -> str:
    lowered = value.lower()
    if "<iframe" in lowered:
        raise ConversionError("프론트 payload iframeHtml에는 중첩 iframe 태그를 저장하지 않는다.")
    if any(token in lowered for token in _FORBIDDEN_TOKENS):
        raise ConversionError("프론트 payload iframeHtml에 금지 sandbox token이 포함됐다.")
    if not _is_document(value):
        return _document(value)
    return value
