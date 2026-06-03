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


# SVG 노드 라벨용 짧은 길이 상한. 눈금·점·카드 항목처럼 짧아야 정상인 텍스트에만 적용한다.
# 메인 내레이션 문장에는 절대 적용하지 않는다(narration_text를 쓴다).
_LABEL_MAX_CHARS = 120
# 메인 내레이션 안전 상한. parse 단계가 narration을 완결 문장으로 보장하고 길이도
# max_length=600으로 제한하므로, 정상 입력은 이 상한에 걸리지 않는다. 비정상 입력만 방어한다.
_NARRATION_SAFETY_CHARS = 1200


def text(value: object, default: str) -> str:
    """SVG 노드 라벨용 — 짧게 자르고 HTML escape한다.

    눈금·점·비교 항목처럼 본래 짧아야 하는 라벨 전용이다. 상한을 넘으면 단어 중간을
    그대로 노출하는 대신 말줄임표(…)를 붙여 절단됐음을 시각적으로 알린다. 메인 내레이션
    문장에는 절대 쓰지 않는다(narration_text 사용).
    """
    raw = str(value) if value not in (None, "") else default
    if len(raw) > _LABEL_MAX_CHARS:
        # 단어 중간 노출 대신 말줄임표로 절단 사실을 드러낸다(라벨은 짧을수록 정상).
        raw = raw[: _LABEL_MAX_CHARS - 1].rstrip() + "…"
    return escape(raw, quote=True)


def narration_text(value: object, default: str) -> str:
    """메인 내레이션(학습자 화면 본문) 전용 — 완결 문장을 절단 없이 HTML escape한다.

    parse 단계(parallel_prompts)가 narration을 완결 문장으로 보장하고 길이를 600자 이내로
    제한하므로, 정상 입력은 그대로 통과한다. 라벨용 120자 cap을 적용하지 않아 문장 중간
    절단이 발생하지 않는다. 비정상적으로 긴 입력(1200자 초과)만 완결 문장 경계에서 자른다.
    """
    raw = str(value) if value not in (None, "") else default
    if len(raw) > _NARRATION_SAFETY_CHARS:
        raw = _trim_to_sentence(raw, _NARRATION_SAFETY_CHARS)
    return escape(raw, quote=True)


def _trim_to_sentence(text_value: str, max_chars: int) -> str:
    """max_chars를 넘는 텍스트를 완결 문장 경계에서만 자른다(단어 중간 절단 금지).

    종결 부호(.!?。！？) 위치 중 max_chars 이하인 가장 마지막 지점까지 보존한다.
    경계가 없으면(부호 없는 단일 긴 문장) 원본을 그대로 반환해 중간 절단을 피한다.
    """
    boundaries = [i for i, ch in enumerate(text_value[:max_chars]) if ch in ".!?。！？"]
    if boundaries:
        return text_value[: boundaries[-1] + 1]
    return text_value


def color(value: object, default: str) -> str:
    """허용된 색상 문자열만 통과시킨다."""
    if isinstance(value, str) and (value.startswith("#") or value.startswith("var(")):
        return escape(value, quote=True)
    return default


def nice(value: float) -> str:
    """정수형 float를 깔끔하게 표기한다."""
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


__all__ = ["axis_x", "card", "color", "coords", "items", "mapping", "narration_text", "nice", "num", "records", "step_card", "svg_block", "text"]
