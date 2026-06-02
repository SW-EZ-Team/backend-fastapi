from __future__ import annotations

import math
from collections.abc import Mapping
from html import escape
from typing import cast


def svg_block(class_name: str, view_box: str, body: str) -> str:
    """공통 SVG 껍데기를 만든다."""
    return f'<svg class="{class_name}" xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" role="img" aria-label="학습 도식">{body}</svg>'


def card(data: Mapping[str, object]) -> str:
    """비교 카드 한 칸을 만든다."""
    title = text(data.get("title"), "비교 항목")
    rows = "".join(f"<li>{text(item, '')}</li>" for item in items(data.get("items"))[:5])
    return f'<article class="comparison-card"><h3>{title}</h3><ul>{rows}</ul></article>'


def step_card(index: int, data: Mapping[str, object]) -> str:
    """단계 카드 한 칸을 만든다."""
    label = text(data.get("label"), f"{index}단계")
    detail = text(data.get("detail"), "조건을 확인한다.")
    result = text(data.get("result"), "결과를 정리한다.")
    return f'<article><b>{index}. {label}</b><p>{detail}</p><strong>{result}</strong></article>'


def coords(nodes: list[Mapping[str, object]]) -> dict[str, tuple[float, float]]:
    """노드 수에 맞춰 관계도 좌표를 원형으로 배치한다."""
    count = max(len(nodes), 1)
    output: dict[str, tuple[float, float]] = {}
    for idx, node in enumerate(nodes):
        angle = -math.pi / 2 + (2 * math.pi * idx / count)
        output[str(node.get("id", idx))] = (360 + 220 * math.cos(angle), 155 + 102 * math.sin(angle))
    return output


def records(value: object) -> list[Mapping[str, object]]:
    """dict 배열만 안전하게 골라낸다."""
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]


def mapping(value: object) -> Mapping[str, object]:
    """객체가 아니면 빈 매핑으로 대체한다."""
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def items(value: object) -> list[object]:
    """배열 값만 반환한다."""
    return value if isinstance(value, list) else []


def num(value: object, default: float) -> float:
    """숫자형 입력을 float로 정규화한다."""
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def axis_x(value: float, min_v: float, max_v: float) -> float:
    """수직선 값을 SVG x 좌표로 바꾼다."""
    ratio = (value - min_v) / (max_v - min_v)
    return 72 + min(max(ratio, 0.0), 1.0) * 566


def text(value: object, default: str) -> str:
    """화면 텍스트를 짧게 자르고 HTML escape한다."""
    raw = str(value) if value not in (None, "") else default
    return escape(raw[:120], quote=True)


def color(value: object, default: str) -> str:
    """허용된 색상 문자열만 통과시킨다."""
    if isinstance(value, str) and (value.startswith("#") or value.startswith("var(")):
        return escape(value, quote=True)
    return default


def nice(value: float) -> str:
    """정수형 float를 깔끔하게 표기한다."""
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


__all__ = ["axis_x", "card", "color", "coords", "items", "mapping", "nice", "num", "records", "step_card", "svg_block", "text"]
