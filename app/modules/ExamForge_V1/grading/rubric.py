"""서술형·논술형·실기형 AI 루브릭 채점."""
from __future__ import annotations

import json
from collections.abc import Mapping

from app.modules.ExamForge_V1.common.ai_bridge import (
    AIConnector,
    ChapterAIRequest,
    get_text_connector,
)
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json
from app.modules.ExamForge_V1.grading.exceptions import RubricGradingError
from app.modules.ExamForge_V1.grading.normalization import answer_to_text
from app.modules.ExamForge_V1.schemas.grading import (
    GradingMode,
    JsonValue,
    QuestionGradeResult,
    RubricCriterionResult,
)
from app.modules.ExamForge_V1.schemas.question import Question

RUBRIC_TEMPLATES: frozenset[str] = frozenset({
    "ko_descriptive",
    "ko_essay",
    "us_essay",
    "engineer_practical",
})

_SYSTEM_PROMPT = (
    "너는 실제 시험 채점관이다. 제공된 정답, 해설, 채점 기준, 원문 근거만 사용해 "
    "학생 답안을 채점한다. 근거 없는 점수 추정, 온정적 가산점, 임의 정답 생성은 금지한다. "
    "반드시 JSON 객체 하나만 출력한다."
)


async def grade_rubric_question(
    question: Question,
    answer: JsonValue,
    connector: AIConnector | None = None,
) -> QuestionGradeResult:
    """실제 AI 커넥터로 루브릭 채점을 수행한다."""
    active_connector = connector or _load_text_connector()
    req = ChapterAIRequest(
        system=_SYSTEM_PROMPT,
        user=_build_user_prompt(question, answer),
        max_tokens=2200,
        temperature=0.0,
        extra={"task": "examforge_rubric_grading"},
    )
    try:
        response = await active_connector.generate(req)
        data = parse_llm_json(response.text)
        return _parse_ai_result(question, data)
    except RubricGradingError:
        raise
    except Exception as exc:
        raise RubricGradingError(f"AI 루브릭 채점 실패: {exc}") from exc


def _load_text_connector() -> AIConnector:
    """production 설정에 등록된 텍스트 커넥터를 불러온다."""
    try:
        return get_text_connector()
    except Exception as exc:
        raise RubricGradingError(f"텍스트 커넥터 초기화 실패: {exc}") from exc


def _build_user_prompt(question: Question, answer: JsonValue) -> str:
    """모델이 채점 외 작업을 하지 못하도록 입력과 출력 계약을 고정한다."""
    payload = {
        "question_id": question.question_id,
        "template_id": question.template_id,
        "stem": question.stem,
        "max_score": question.points,
        "model_answer": question.correct_answer,
        "explanation_and_scoring_criteria": question.explanation,
        "source_reference": question.source_reference,
        "student_answer": answer_to_text(answer),
    }
    contract = {
        "score": "0 이상 max_score 이하의 숫자",
        "feedback": "학생에게 보여줄 한두 문장 채점 피드백",
        "confidence": "0.0 이상 1.0 이하의 숫자",
        "needs_manual_review": "채점 근거가 부족하면 true",
        "rubric_breakdown": [
            {
                "criterion": "채점 기준명",
                "score": "기준별 취득점",
                "max_score": "기준별 만점",
                "reason": "점수 근거",
            }
        ],
    }
    return (
        "[채점 입력]\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "[출력 JSON 계약]\n"
        f"{json.dumps(contract, ensure_ascii=False, indent=2)}\n\n"
        "주의: 출력은 JSON 객체 하나여야 하며, markdown 코드블록과 설명문을 붙이지 마시오."
    )


def _parse_ai_result(question: Question, data: object) -> QuestionGradeResult:
    """AI 응답을 내부 채점 결과로 엄격하게 변환한다."""
    if not isinstance(data, Mapping):
        raise RubricGradingError("AI 채점 응답이 JSON 객체가 아니다.")
    max_score = max(float(question.points), 0.01)
    score = _required_number(data, "score")
    confidence = _required_number(data, "confidence")
    feedback = _required_text(data, "feedback")
    manual = _required_bool(data, "needs_manual_review")
    breakdown = _parse_breakdown(data.get("rubric_breakdown"))
    _validate_breakdown_score(score, max_score, breakdown)
    final_score = min(max(score, 0.0), max_score)
    return QuestionGradeResult(
        question_id=question.question_id,
        template_id=question.template_id,
        score=round(final_score, 4),
        max_score=round(max_score, 4),
        is_correct=final_score >= max_score,
        grading_mode=GradingMode.AI_RUBRIC,
        feedback=feedback,
        rubric_breakdown=breakdown,
        confidence=min(max(confidence, 0.0), 1.0),
        needs_manual_review=manual,
    )


def _parse_breakdown(value: object) -> list[RubricCriterionResult]:
    """루브릭 세부 항목 배열을 검증한다."""
    if not isinstance(value, list) or not value:
        raise RubricGradingError("rubric_breakdown은 비어 있지 않은 배열이어야 한다.")
    results: list[RubricCriterionResult] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise RubricGradingError("rubric_breakdown 항목이 객체가 아니다.")
        results.append(
            RubricCriterionResult(
                criterion=_required_text(item, "criterion"),
                score=max(_required_number(item, "score"), 0.0),
                max_score=max(_required_number(item, "max_score"), 0.01),
                reason=_required_text(item, "reason"),
            )
        )
    return results


def _required_number(data: Mapping[object, object], key: str) -> float:
    """필수 숫자 필드를 읽는다."""
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RubricGradingError(f"{key} 필드는 숫자여야 한다.")
    return float(value)


def _required_text(data: Mapping[object, object], key: str) -> str:
    """필수 문자열 필드를 읽는다."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RubricGradingError(f"{key} 필드는 비어 있지 않은 문자열이어야 한다.")
    return value.strip()


def _required_bool(data: Mapping[object, object], key: str) -> bool:
    """필수 불리언 필드를 읽는다."""
    value = data.get(key)
    if not isinstance(value, bool):
        raise RubricGradingError(f"{key} 필드는 boolean이어야 한다.")
    return value


def _validate_breakdown_score(
    score: float,
    max_score: float,
    breakdown: list[RubricCriterionResult],
) -> None:
    """총점과 세부 루브릭 합계가 서로 모순되지 않는지 검증한다."""
    score_sum = sum(item.score for item in breakdown)
    max_sum = sum(item.max_score for item in breakdown)
    for item in breakdown:
        if item.score > item.max_score + 0.05:
            raise RubricGradingError("루브릭 항목 점수가 항목 만점을 초과했다.")
    if abs(score_sum - score) > 0.05:
        raise RubricGradingError("AI 채점 총점과 루브릭 세부 점수 합계가 다르다.")
    if abs(max_sum - max_score) > 0.05:
        raise RubricGradingError("문항 만점과 루브릭 세부 만점 합계가 다르다.")
