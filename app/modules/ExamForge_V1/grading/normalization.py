"""답안 정규화 유틸리티."""
from __future__ import annotations

import json
import re

from app.modules.ExamForge_V1.schemas.grading import JsonValue

_PAIR_SEPARATORS = ("->", "=>", ":", "=", "-")
_META_KEYS = {"answer", "value", "text", "selected", "choice", "response"}


def normalize_text(value: object) -> str:
    """비교용 문자열을 소문자와 단일 공백 형태로 맞춘다."""
    text = str(value).strip().lower()
    return re.sub(r"\s+", " ", text)


def compact_text(value: object) -> str:
    """정답 비교에서 조사나 공백 단서가 끼지 않게 문장부호를 제거한다."""
    return re.sub(r"[\W_]+", "", normalize_text(value), flags=re.UNICODE)


def answer_to_text(value: JsonValue) -> str:
    """답안 페이로드를 루브릭 채점용 원문 문자열로 변환한다."""
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    if isinstance(value, int | float | bool):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def scalar_text(value: JsonValue) -> str:
    """객관식/단답형 답안에서 대표 문자열 하나를 꺼낸다."""
    if isinstance(value, dict):
        for key in _META_KEYS:
            if key in value:
                return scalar_text(value[key])
        return answer_to_text(value)
    if isinstance(value, list):
        return "" if not value else scalar_text(value[0])
    return answer_to_text(value)


def sequence_values(value: JsonValue) -> list[str]:
    """빈칸/순서형 답안을 순서가 있는 문자열 목록으로 바꾼다."""
    if isinstance(value, list):
        return [scalar_text(item) for item in value]
    if isinstance(value, dict):
        for key in ("answers", "values", "blanks", "order", "sequence", "items"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [scalar_text(item) for item in nested]
        return [scalar_text(value[key]) for key in sorted(value.keys())]
    text = scalar_text(value)
    return split_sequence_text(text)


def split_sequence_text(text: str) -> list[str]:
    """쉼표나 줄바꿈으로 입력된 순서 답안을 목록으로 분해한다."""
    parts = re.split(r"[,;\n>]+", text)
    return [part.strip() for part in parts if part.strip()]


def accepted_variants(text: str) -> set[str]:
    """정답 문자열에서 허용 답안 후보를 추출한다."""
    raw = [text]
    for sep in ("|", "/", ";", ",", "\n", " 또는 ", " 혹은 "):
        expanded: list[str] = []
        for item in raw:
            expanded.extend(item.split(sep))
        raw = expanded
    return {compact_text(item) for item in raw if compact_text(item)}


def mapping_values(value: JsonValue) -> dict[str, str]:
    """연결형 답안을 좌항-우항 매핑으로 변환한다."""
    if isinstance(value, dict):
        nested = value.get("pairs")
        if nested is not None:
            return mapping_values(nested)
        return {
            normalize_text(key): scalar_text(raw)
            for key, raw in value.items()
            if key not in _META_KEYS and key != "pairs"
        }
    if isinstance(value, list):
        return _mapping_from_list(value)
    return _mapping_from_text(scalar_text(value))


def _mapping_from_list(items: list[JsonValue]) -> dict[str, str]:
    """배열형 연결 답안을 매핑으로 변환한다."""
    result: dict[str, str] = {}
    for item in items:
        if isinstance(item, dict):
            left = item.get("left") or item.get("from") or item.get("key")
            right = item.get("right") or item.get("to") or item.get("value")
            if left is not None and right is not None:
                result[normalize_text(left)] = scalar_text(right)
    return result


def _mapping_from_text(text: str) -> dict[str, str]:
    """문자열 연결 답안을 매핑으로 변환한다."""
    result: dict[str, str] = {}
    for raw_pair in re.split(r"[,;\n]+", text):
        pair = raw_pair.strip()
        for sep in _PAIR_SEPARATORS:
            if sep in pair:
                left, right = pair.split(sep, 1)
                result[normalize_text(left)] = right.strip()
                break
    return result
