from __future__ import annotations

import nh3

BASE_ALLOWED_TAGS = {
    "div", "span", "p", "section", "article", "header", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "pre", "code",
    "blockquote", "strong", "em", "b", "i", "u", "s", "small", "sub", "sup",
    "a", "img", "br", "hr", "svg", "path", "circle", "rect", "line",
    "polyline", "polygon", "text", "g", "defs", "use", "symbol",
}
INTERACTIVE_EXTRA_TAGS = {"button", "details", "summary"}
BASE_ALLOWED_ATTRS = {
    "*": {"class", "id", "aria-label", "aria-hidden", "role"},
    "a": {"href", "target"},
    "button": {"type"},
    "circle": {"cx", "cy", "r", "fill", "stroke", "stroke-width", "transform"},
    "code": {"data-lang"},
    "details": {"open"},
    "div": {"data-chart-type", "data-chart-spec"},
    "g": {"fill", "stroke", "stroke-width", "transform"},
    "img": {"src", "alt", "width", "height"},
    "line": {"x1", "y1", "x2", "y2", "fill", "stroke", "stroke-width", "transform"},
    "path": {"d", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "transform"},
    "polygon": {"points", "fill", "stroke", "stroke-width", "transform"},
    "polyline": {"points", "fill", "stroke", "stroke-width", "transform"},
    "pre": {"class"},
    "rect": {"x", "y", "rx", "ry", "width", "height", "fill", "stroke", "stroke-width", "transform"},
    "svg": {"xmlns", "viewBox", "width", "height", "fill", "stroke"},
    "td": {"colspan", "rowspan"},
    "text": {"x", "y", "dx", "dy", "fill", "stroke", "font-size", "text-anchor", "transform"},
    "th": {"colspan", "rowspan"},
    "use": {"href", "x", "y", "width", "height", "transform"},
}


def sanitize(source_html: str, category: str) -> str:
    """카테고리별 허용 태그만 남기고 외부 URL은 전부 제거한다."""
    tags = set(BASE_ALLOWED_TAGS)
    if category == "interactive":
        tags |= INTERACTIVE_EXTRA_TAGS
    attrs = {key: value for key, value in BASE_ALLOWED_ATTRS.items() if key == "*" or key in tags}
    return nh3.clean(
        source_html,
        tags=tags,
        attributes=attrs,
        attribute_filter=_attribute_filter,
        url_schemes={"data"},
        strip_comments=True,
    )


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    """차트 data 이미지만 보존하고 외부 URL은 모두 제거한다."""
    if tag == "img" and attr == "src":
        return value if value.startswith("data:image/png;base64,") else None
    if attr == "href":
        return value if value.startswith("#") else None
    return value
