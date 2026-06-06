"""객관식과 구조화 문항의 결정론 채점."""
from __future__ import annotations

from app.modules.ExamForge_V1.grading.normalization import (
    accepted_variants,
    compact_text,
    mapping_values,
    normalize_text,
    scalar_text,
    sequence_values,
    split_sequence_text,
)
from app.modules.ExamForge_V1.schemas.grading import (
    GradeQuestion,
    GradingMode,
    JsonValue,
    QuestionGradeResult,
    RubricCriterionResult,
)

_CHOICE_TEMPLATES = {
    "ko_multiple_choice_4", "ko_multiple_choice_5",
    "us_multiple_choice_4", "us_multiple_choice_5",
    "engineer_written", "cert_base",
}
_TRUE_FALSE_TEMPLATES = {"ko_true_false", "us_true_false"}
_SHORT_TEMPLATES = {"ko_short_answer", "us_short_answer"}
_BLANK_TEMPLATES = {"ko_fill_blank", "us_fill_blank"}
_ORDER_TEMPLATES = {"ko_ordering", "us_ordering"}
_MATCH_TEMPLATES = {"ko_matching", "us_matching"}


def grade_objective_question(
    question: GradeQuestion,
    answer: JsonValue,
) -> QuestionGradeResult:
    """템플릿별 결정론 채점기를 선택한다."""
    template_id = question.template_id
    if template_id in _CHOICE_TEMPLATES:
        return grade_choice_question(question, answer)
    if template_id in _TRUE_FALSE_TEMPLATES:
        return grade_true_false_question(question, answer)
    if template_id in _BLANK_TEMPLATES:
        return grade_blank_question(question, answer)
    if template_id in _ORDER_TEMPLATES:
        return grade_ordering_question(question, answer)
    if template_id in _MATCH_TEMPLATES:
        return grade_matching_question(question, answer)
    if template_id in _SHORT_TEMPLATES:
        return grade_exact_question(question, answer)
    return grade_exact_question(question, answer)


def grade_unanswered_question(question: Question) -> QuestionGradeResult:
    """미제출 문항을 0점으로 채점한다."""
    return _result(question, 0.0, "답안 미제출", [])


def grade_exact_question(question: Question, answer: JsonValue) -> QuestionGradeResult:
    """단답형과 실기형의 명시 허용 답안을 정확히 비교한다."""
    candidate = compact_text(scalar_text(answer))
    accepted = accepted_variants(question.correct_answer)
    score = _points(question) if candidate in accepted else 0.0
    reason = "허용 답안과 일치" if score else "허용 답안과 불일치"
    return _result(question, score, reason, [_criterion("정답 일치", score, question, reason)])


def grade_choice_question(question: Question, answer: JsonValue) -> QuestionGradeResult:
    """보기 label, 보기 문장, correct_answer를 모두 정답 후보로 인정한다."""
    candidate = compact_text(scalar_text(answer))
    accepted = set(accepted_variants(question.correct_answer))
    for option in question.options or []:
        if option.is_correct:
            accepted.add(compact_text(option.label))
            accepted.add(compact_text(option.text))
    score = _points(question) if candidate in accepted else 0.0
    reason = "정답 보기 선택" if score else "오답 보기 선택"
    return _result(question, score, reason, [_criterion("보기 선택", score, question, reason)])


def grade_true_false_question(question: Question, answer: JsonValue) -> QuestionGradeResult:
    """O/X, 참/거짓, true/false 표기를 같은 의미로 정규화한다."""
    candidate = _bool_token(scalar_text(answer))
    accepted = {_bool_token(item) for item in accepted_variants(question.correct_answer)}
    accepted.discard("")
    score = _points(question) if candidate and candidate in accepted else 0.0
    reason = "참거짓 판정 일치" if score else "참거짓 판정 불일치"
    return _result(question, score, reason, [_criterion("참거짓", score, question, reason)])


def grade_blank_question(question: Question, answer: JsonValue) -> QuestionGradeResult:
    """빈칸별 정답을 위치 기준 부분점수로 채점한다."""
    expected = question.blank_answers or split_sequence_text(question.correct_answer)
    if not expected:
        return grade_exact_question(question, answer)
    submitted = sequence_values(answer)
    unit = _points(question) / len(expected)
    criteria: list[RubricCriterionResult] = []
    score = 0.0
    for index, correct in enumerate(expected):
        candidate = compact_text(submitted[index]) if index < len(submitted) else ""
        ok = candidate in accepted_variants(correct)
        item_score = unit if ok else 0.0
        score += item_score
        reason = "일치" if ok else "불일치"
        criteria.append(_criterion(f"빈칸 {index + 1}", item_score, question, reason, unit))
    return _result(question, score, "빈칸 위치별 채점", criteria)


def grade_ordering_question(question: Question, answer: JsonValue) -> QuestionGradeResult:
    """정답 순서와 같은 위치에 놓인 항목 수로 부분점수를 계산한다."""
    expected = question.correct_ordering or split_sequence_text(question.correct_answer)
    if not expected:
        return grade_exact_question(question, answer)
    submitted = sequence_values(answer)
    unit = _points(question) / len(expected)
    score = 0.0
    criteria: list[RubricCriterionResult] = []
    for index, correct in enumerate(expected):
        ok = index < len(submitted) and compact_text(submitted[index]) == compact_text(correct)
        item_score = unit if ok else 0.0
        score += item_score
        reason = "순서 일치" if ok else "순서 불일치"
        criteria.append(_criterion(f"순서 {index + 1}", item_score, question, reason, unit))
    return _result(question, score, "순서 위치별 채점", criteria)


def grade_matching_question(question: Question, answer: JsonValue) -> QuestionGradeResult:
    """좌항별 연결 우항을 비교해 부분점수를 계산한다."""
    expected = {pair.left: pair.right for pair in question.matching_pairs or []}
    if not expected:
        return grade_exact_question(question, answer)
    submitted = mapping_values(answer)
    unit = _points(question) / len(expected)
    score = 0.0
    criteria: list[RubricCriterionResult] = []
    for left, right in expected.items():
        candidate = compact_text(submitted.get(normalize_text(left), ""))
        ok = candidate == compact_text(right)
        item_score = unit if ok else 0.0
        score += item_score
        reason = "연결 일치" if ok else "연결 불일치"
        criteria.append(_criterion(left, item_score, question, reason, unit))
    return _result(question, score, "연결 항목별 채점", criteria)


def _bool_token(value: str) -> str:
    """국문/영문 참거짓 표기를 내부 토큰으로 맞춘다."""
    normalized = compact_text(value)
    if normalized in {"o", "true", "t", "yes", "y", "참", "맞음", "옳음"}:
        return "true"
    if normalized in {"x", "false", "f", "no", "n", "거짓", "틀림", "그름"}:
        return "false"
    return normalized


def _points(question: Question) -> float:
    """문항 배점을 양수로 보정한다."""
    return max(float(question.points), 0.01)


def _criterion(
    name: str,
    score: float,
    question: GradeQuestion,
    reason: str,
    max_score: float | None = None,
) -> RubricCriterionResult:
    """결정론 채점도 루브릭과 같은 응답 구조로 맞춘다."""
    return RubricCriterionResult(
        criterion=name,
        score=round(score, 4),
        max_score=round(max_score if max_score is not None else _points(question), 4),
        reason=reason,
    )


def _result(
    question: GradeQuestion,
    score: float,
    feedback: str,
    criteria: list[RubricCriterionResult],
) -> QuestionGradeResult:
    """공통 문항 결과를 만든다."""
    max_score = _points(question)
    final_score = min(max(score, 0.0), max_score)
    return QuestionGradeResult(
        question_id=question.question_id,
        template_id=question.template_id,
        score=round(final_score, 4),
        max_score=round(max_score, 4),
        is_correct=final_score >= max_score,
        grading_mode=GradingMode.DETERMINISTIC,
        feedback=feedback,
        rubric_breakdown=criteria,
        confidence=1.0,
        needs_manual_review=False,
    )
