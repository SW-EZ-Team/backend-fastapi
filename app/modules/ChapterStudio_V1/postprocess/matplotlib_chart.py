from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import re
from collections.abc import Sequence
from functools import lru_cache

from app.modules.ChapterStudio_V1.common.config import prepare_matplotlib_runtime

_CHART_RE = re.compile(
    r"<div\b(?=[^>]*\bclass=(?P<class_quote>['\"])[^'\"]*\bchart-box\b[^'\"]*(?P=class_quote))"
    r"(?P<attrs>[^>]*)>\s*</div>|"
    r"<div\b(?=[^>]*\bclass=(?P<class_quote_open>['\"])[^'\"]*\bchart-box\b[^'\"]*(?P=class_quote_open))"
    r"(?P<open_attrs>[^>]*)>",
    re.DOTALL,
)
_ATTR_RE = re.compile(r"\b(?P<name>data-chart-type|data-chart-spec)=(?P<quote>['\"])(?P<value>.*?)(?P=quote)", re.DOTALL)


async def chart_render(source_html: str) -> tuple[str, list[str]]:
    """data-chart payload를 PNG data URI 이미지로 치환한다."""
    warnings: list[str] = []
    parts: list[str] = []
    last = 0
    for match in _CHART_RE.finditer(source_html):
        parts.append(source_html[last:match.start()])
        attrs = match.group("attrs") or match.group("open_attrs") or ""
        chart_type = _attr_value(attrs, "data-chart-type")
        spec = _attr_value(attrs, "data-chart-spec")
        tag, warning = await _render_chart(chart_type, spec, match.group(0))
        parts.append(tag)
        if warning is not None:
            warnings.append(warning)
        last = match.end()
    parts.append(source_html[last:])
    return "".join(parts), warnings


def _attr_value(attrs: str, name: str) -> str:
    for match in _ATTR_RE.finditer(attrs):
        if match.group("name") == name:
            return match.group("value")
    return ""


async def _render_chart(chart_type: str, raw_spec: str, fallback: str) -> tuple[str, str | None]:
    if not chart_type or not raw_spec:
        return fallback, "matplotlib: 차트 렌더링 실패 data-chart-type 또는 data-chart-spec 누락"
    try:
        loop = asyncio.get_running_loop()
        tag = await loop.run_in_executor(None, _render_chart_cached, chart_type, raw_spec)
        return tag, None
    except (ValueError, TypeError, binascii.Error, RuntimeError) as exc:
        return fallback, f"matplotlib: 차트 렌더링 실패 {exc}"


def _decode_spec(raw_spec: str) -> dict[str, object]:
    try:
        decoded = base64.b64decode(raw_spec).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        decoded = raw_spec
    parsed = json.loads(decoded)
    if not isinstance(parsed, dict):
        raise ValueError("차트 spec은 object여야 한다.")
    return parsed


@lru_cache(maxsize=128)
def _render_chart_cached(chart_type: str, raw_spec: str) -> str:
    """같은 차트 spec은 PNG 재생성을 피한다."""
    return _render_chart_sync(chart_type, _decode_spec(raw_spec))


def _render_chart_sync(chart_type: str, spec: dict[str, object]) -> str:
    prepare_matplotlib_runtime()
    import matplotlib

    matplotlib.use("Agg")
    _configure_korean_font()
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.4, 3.8), dpi=120)
    fig.patch.set_facecolor("#FFFDF7")
    ax.set_facecolor("#FFFDF7")
    values = _chart_values(spec)
    labels = _chart_labels(spec, len(values))
    colors = _color_list(spec.get("colors"), len(values))
    if chart_type == "bar":
        ax.bar(labels, values, color=colors)
    elif chart_type == "line":
        ax.plot(labels, values, color=colors[0], marker="o", linewidth=2.4)
    elif chart_type == "scatter":
        ax.scatter(list(range(len(values))), values, color=colors, s=72)
    elif chart_type == "pie":
        ax.pie(values, labels=labels, colors=colors)
    elif chart_type == "histogram":
        ax.hist(values, color=colors[0])
    else:
        raise ValueError(f"지원하지 않는 차트 타입: {chart_type}")
    _decorate(ax, spec)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    image = base64.b64encode(buf.getvalue()).decode()
    return f'<img class="rendered-chart" src="data:image/png;base64,{image}" alt="분류별 색상 차트" />'


def _configure_korean_font() -> None:
    import matplotlib
    from matplotlib import font_manager

    names = {font.name for font in font_manager.fontManager.ttflist}
    for family in ("AppleGothic", "NanumGothic", "Noto Sans CJK KR", "Arial Unicode MS"):
        if family in names:
            matplotlib.rcParams["font.family"] = [family]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return


def _nested(spec: dict[str, object], first: str, second: str) -> object:
    data = spec.get(first)
    if not isinstance(data, dict):
        return ()
    return data.get(second, ())


def _str_list(value: object, count: int) -> list[str]:
    if isinstance(value, str):
        return [value] if count == 1 else [f"{value} {idx + 1}" for idx in range(count)]
    if not isinstance(value, Sequence):
        return [f"항목 {idx + 1}" for idx in range(count)]
    labels = [str(item) for item in value][:count]
    if len(labels) < count:
        labels.extend(f"항목 {idx + 1}" for idx in range(len(labels), count))
    return labels


def _float_list(value: object) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ValueError("values는 숫자 배열이어야 한다.")
    values = [float(item) for item in value]
    if not values:
        raise ValueError("values는 비어 있으면 안 된다.")
    return values


def _chart_values(spec: dict[str, object]) -> list[float]:
    """LLM이 자주 쓰는 x/y 차트 spec도 내부 values 계약으로 흡수한다."""
    raw_values = _nested(spec, "data", "values")
    if _is_empty_sequence(raw_values):
        raw_values = _nested(spec, "data", "y")
    return _float_list(raw_values)


def _chart_labels(spec: dict[str, object], count: int) -> list[str]:
    """x축 배열이 labels 대신 온 경우에도 화면에 읽히는 축 이름을 만든다."""
    raw_labels = _nested(spec, "data", "labels")
    if _is_empty_sequence(raw_labels):
        raw_labels = _nested(spec, "data", "x")
    return _str_list(raw_labels, count)


def _is_empty_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str) and len(value) == 0


def _color_list(value: object, count: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return _default_colors(count)
    colors = [str(item) for item in value if isinstance(item, str) and item.startswith("#")]
    return (colors + _default_colors(count))[:count]


def _default_colors(count: int) -> list[str]:
    base = ["#2A3B45", "#207B4C", "#7A6518", "#C2425B", "#36B36F"]
    return [base[idx % len(base)] for idx in range(count)]


def _decorate(ax: object, spec: dict[str, object]) -> None:
    for key, setter in {"title": "set_title", "x_label": "set_xlabel", "y_label": "set_ylabel"}.items():
        value = spec.get(key)
        if isinstance(value, str):
            getattr(ax, setter)(value)
    getattr(ax, "grid")(axis="y", color="#ECE6D8", linewidth=0.8)
