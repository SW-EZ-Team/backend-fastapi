"""강의 산출물 파싱 전 방어적 정규화.

Qwen3.6(Modal)이 xgrammar guided_json을 쓰면서도 `list[str]`을 기대하는 자리에 dict나
str을 보내는 사례가 실측됐다(예: assignment.rubric={"correctness":"..."}, rubric="...").
codex(gpt-5.5)는 이미 list로 주므로 이 패스는 codex 출력에서 no-op가 되도록 설계한다 —
list/누락/그 외 잘못된 타입은 손대지 않고 dict/str만 list로 평탄화한다.

공개 API:
    - normalize_lesson_dict(data) : assignment 내 list 기대 필드의 dict/str을 list로 평탄화한다.

이 모듈은 어떤 LLM도 호출하지 않는 순수 함수만 둔다(부수효과 없음, 입력 비파괴).
"""
from __future__ import annotations

import re
from typing import Any

# assignment에서 `list[str]`을 기대하지만 모델이 dict로 보낼 수 있는 필드들.
_ASSIGNMENT_LIST_FIELDS = ("steps", "rubric")
_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)")
_INLINE_NUMBERED_ITEM = re.compile(r"(?:^|\s+)(?=\d+[.)]\s+)")


def normalize_lesson_dict(data: Any) -> Any:
    """파싱 전 강의 dict를 방어적으로 정규화한다(입력 비파괴, dict일 때만 동작).

    최상위가 dict가 아니면 그대로 돌려준다(다운스트림 strict 검증이 최종 판단).
    assignment 안의 list 기대 필드가 dict/str이면 문자열 리스트로 평탄화한다.
    """
    if not isinstance(data, dict):
        return data
    assignment = data.get("assignment")
    if not isinstance(assignment, dict):
        return data
    fixed_assignment = _normalize_assignment(assignment)
    if fixed_assignment is assignment:
        return data
    return {**data, "assignment": fixed_assignment}


def normalize_assignment_value(assignment: Any) -> Any:
    """단일 assignment 객체의 steps/rubric dict/str을 list로 평탄화한다(컴포넌트 경로용).

    컴포넌트 병렬 생성에서 assignment만 따로 받을 때 쓰는 공개 헬퍼다. dict가 아니면
    그대로 돌려주고(다운스트림 strict 검증이 최종 판단), dict면 _normalize_assignment를
    재사용해 steps/rubric을 list[str]로 보장한다.
    """
    if not isinstance(assignment, dict):
        return assignment
    return _normalize_assignment(assignment)


def _normalize_assignment(assignment: dict[str, Any]) -> dict[str, Any]:
    """assignment의 steps/rubric이 dict/str이면 list로 바꾼 새 dict를 반환한다(불변이면 원본)."""
    patched: dict[str, Any] = {}
    for field_name in _ASSIGNMENT_LIST_FIELDS:
        value = assignment.get(field_name)
        if isinstance(value, dict):
            patched[field_name] = _dict_to_str_list(value)
        elif isinstance(value, str):
            patched[field_name] = _str_to_str_list(value)
    if not patched:
        return assignment
    return {**assignment, **patched}


def _dict_to_str_list(value: dict[str, Any]) -> list[str]:
    """{"correctness":"X"} 형태를 ["correctness: X"] 문자열 리스트로 평탄화한다.

    값이 문자열이 아니면(중첩 dict/숫자 등) 사람이 읽을 수 있게 str로 강제한다 —
    다운스트림이 어떤 경우에도 list[str] 계약을 받도록 보장하기 위함이다.
    """
    rows: list[str] = []
    for key, raw in value.items():
        text = raw if isinstance(raw, str) else str(raw)
        cleaned = text.strip()
        rows.append(f"{key}: {cleaned}" if cleaned else str(key))
    return rows


def _str_to_str_list(value: str) -> list[str]:
    """문자열 rubric/steps를 list[str]로 변환한다.

    줄바꿈 목록이나 `1. ... 2. ...` 같은 인라인 번호 목록이면 항목을 나누고,
    단일 문장이면 하나의 항목으로 감싼다. 빈 문자열은 빈 리스트로 둬 downstream
    min_length 검증이 실패를 드러내게 한다.
    """
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    lines = [_clean_list_item(line) for line in normalized.split("\n")]
    line_items = [line for line in lines if line]
    if len(line_items) > 1:
        return line_items

    inline_items = [_clean_list_item(item) for item in _INLINE_NUMBERED_ITEM.split(normalized)]
    inline_items = [item for item in inline_items if item]
    if len(inline_items) > 1:
        return inline_items

    cleaned = _clean_list_item(normalized)
    return [cleaned] if cleaned else []


def _clean_list_item(value: str) -> str:
    """불릿/번호 prefix와 양끝 공백을 제거한다."""
    return _BULLET_PREFIX.sub("", value).strip()


__all__ = ["normalize_assignment_value", "normalize_lesson_dict"]
