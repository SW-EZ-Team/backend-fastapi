"""객관식 해설 품질 검사."""
from __future__ import annotations


def check_explanation_quality(question: dict) -> list[str]:
    """정답 근거와 오답별 오개념 설명이 있는지 확인한다."""
    options = question.get("options") or []
    explanation = str(question.get("explanation", "")).strip()
    if len(options) < 4 or not explanation:
        return []
    issues: list[str] = []
    if "정답" not in explanation and str(question.get("correct_answer", "")) not in explanation:
        issues.append("해설에 정답 근거가 없음")
    missing = [
        str(option.get("label", ""))
        for option in options
        if not option.get("is_correct")
        and not _mentions_option(explanation, str(option.get("label", "")))
    ]
    if missing:
        issues.append(f"오답별 해설 누락: {', '.join(missing)}")
    if explanation[-1:] not in (".", "!", "?", "다", "요"):
        issues.append("해설이 완결 문장으로 끝나지 않음")
    return issues


def _mentions_option(explanation: str, label: str) -> bool:
    """해설이 해당 보기 번호/기호를 직접 언급하는지 확인한다."""
    if not label:
        return False
    patterns = (f"{label}번", f"{label}.", f"{label})", f"보기 {label}", f"{label}는")
    return any(pattern in explanation for pattern in patterns)
