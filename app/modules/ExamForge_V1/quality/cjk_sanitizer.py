from __future__ import annotations

from app.modules.ChapterStudio_V1.pipeline.cjk_text import strip_cjk

_QUESTION_TEXT_FIELDS = (
    "topic",
    "stem",
    "explanation",
    "source_reference",
    "distractor_rationale",
)
_OPTION_TEXT_FIELDS = ("text",)
_PAIR_TEXT_FIELDS = ("left", "right")
_TEXT_LIST_FIELDS = ("ordering_items", "correct_ordering", "blank_answers")


def sanitize_exam_question(question: dict) -> dict:
    """모의고사 문항의 사용자 표시 문자열에서 비한글 CJK를 제거한다."""
    cleaned = dict(question)
    for field in _QUESTION_TEXT_FIELDS:
        if field in cleaned:
            cleaned[field] = _sanitize_value(cleaned[field])
    if isinstance(cleaned.get("options"), list):
        cleaned["options"] = [_sanitize_text_dict(option, _OPTION_TEXT_FIELDS) for option in cleaned["options"]]
    if isinstance(cleaned.get("matching_pairs"), list):
        cleaned["matching_pairs"] = [_sanitize_text_dict(pair, _PAIR_TEXT_FIELDS) for pair in cleaned["matching_pairs"]]
    for field in _TEXT_LIST_FIELDS:
        if field in cleaned:
            cleaned[field] = _sanitize_text_list(cleaned[field])
    return cleaned


def sanitize_exam_questions(questions: list[dict]) -> list[dict]:
    """문항 목록을 원본 변이 없이 CJK 정리된 복사본으로 만든다."""
    return [sanitize_exam_question(question) for question in questions]


def _sanitize_text_dict(value: object, fields: tuple[str, ...]) -> object:
    if not isinstance(value, dict):
        return value
    cleaned = dict(value)
    for field in fields:
        if field in cleaned:
            cleaned[field] = _sanitize_value(cleaned[field])
    return cleaned


def _sanitize_text_list(value: object) -> object:
    if not isinstance(value, list):
        return value
    return [_sanitize_value(item) for item in value]


def _sanitize_value(value: object) -> object:
    if isinstance(value, str):
        return strip_cjk(value)
    return value


__all__ = ["sanitize_exam_question", "sanitize_exam_questions"]
