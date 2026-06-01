"""ExamForge 응답 → Spring public.mock_exam_question 행 변환 (순수 함수).

Spring MockExamQuestion 엔티티가 읽는 형태로 정규화한다:
- options: 보기 텍스트만 담은 JSON 배열 문자열 (예: '["보기1","보기2",...]')
- correct_option: 0-based 인덱스 문자열 (options 배열 내 정답 위치)
- question_type: 'multiple_choice' 고정(Spring 채점이 객관식 단일 정답을 가정)
- points: 정수(Spring points 컬럼은 INTEGER NOT NULL DEFAULT 5)

ExamForge Question의 정답 계약(consistency_checker 기준):
객관식은 options[].label 이 보기 식별자이고 correct_answer == 정답 보기의 label,
is_correct=True 인 보기와 일치한다. 따라서 정답 인덱스는
'is_correct=True 인 보기' 또는 'label == correct_answer 인 보기'의 위치다.
"""
from __future__ import annotations

import json
from typing import Any


def to_question_rows(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ExamForge 문제 목록을 Spring mock_exam_question 행 목록으로 변환한다.

    객관식(options 보유)만 채택한다. Spring 채점은 correct_option 단일 인덱스를
    가정하므로 보기가 없는 서술형/순서형 등은 Spring 모의고사 스키마와 호환되지 않아
    제외한다(저장 누락은 호출부가 갯수로 감지).
    """
    rows: list[dict[str, Any]] = []
    idx = 1
    for q in questions:
        row = _to_single_row(q, idx)
        if row is None:
            continue
        rows.append(row)
        idx += 1
    return rows


def _to_single_row(q: dict[str, Any], question_idx: int) -> dict[str, Any] | None:
    """단일 ExamForge 문제를 행으로 변환한다. 객관식이 아니면 None."""
    options = q.get("options")
    if not isinstance(options, list) or len(options) < 2:
        return None

    texts = [str(_opt_get(o, "text", "")).strip() for o in options]
    correct_index = _resolve_correct_index(options, q.get("correct_answer"))
    if correct_index is None:
        return None

    stem = str(q.get("stem") or "").strip()
    if not stem:
        return None

    return {
        "question_idx": question_idx,
        "question_text": stem,
        "question_type": "multiple_choice",
        # 보기 텍스트만 JSON 배열로 — Spring은 인덱스로 정답을 대조한다
        "options": json.dumps(texts, ensure_ascii=False),
        "correct_option": str(correct_index),  # 0-based 인덱스 문자열
        "explanation": str(q.get("explanation") or "").strip(),
        "points": _coerce_points(q.get("points")),
    }


def _resolve_correct_index(options: list[Any], correct_answer: Any) -> int | None:
    """정답 보기의 0-based 인덱스를 구한다.

    우선순위: 1) is_correct=True 인 보기, 2) label == correct_answer 인 보기.
    둘 다 실패하면 None(매핑 불가 → 저장 제외).
    """
    for i, opt in enumerate(options):
        if _opt_get(opt, "is_correct", False):
            return i

    if correct_answer is not None:
        target = str(correct_answer).strip()
        if target:
            for i, opt in enumerate(options):
                if str(_opt_get(opt, "label", "")).strip() == target:
                    return i
    return None


def _opt_get(opt: Any, key: str, default: Any) -> Any:
    """보기 항목이 dict이든 Pydantic 모델이든 동일하게 필드를 읽는다."""
    if isinstance(opt, dict):
        return opt.get(key, default)
    return getattr(opt, key, default)


def _coerce_points(value: Any) -> int:
    """points를 정수로 변환한다(Spring INTEGER 컬럼). 실패 시 기본 5점."""
    if not isinstance(value, (int, float, str)):
        return 5
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return 5
    return n if n > 0 else 5
