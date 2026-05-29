"""API 응답 모델."""
from __future__ import annotations

from pydantic import BaseModel

from .question import Question
from .exam_plan import ExamPlan


class QualityMetrics(BaseModel):
    """품질 지표."""

    answer_accuracy_rate: float
    dedup_score: float
    coverage_score: float
    # Round 4 수정 이후 metrics.py가 생성하는 키 이름에 맞춤
    distractor_plausibility_score: float
    # 문제 줄기 길이 분산 비율 (metrics.py에서 추가된 신규 필드)
    length_variance_ratio: float
    bloom_distribution_actual: dict[str, float]
    retry_count: int
    generation_time_sec: float


class ExamForgeResponse(BaseModel):
    """모의고사 응답."""

    exam_id: str
    exam_plan: ExamPlan
    questions: list[Question]
    quality_metrics: QualityMetrics
    # "passed": 품질 기준 통과, "exhausted": 최대 재시도 횟수 소진 후 종료
    pipeline_outcome: str
    answer_key_seal: str | None = None
    exam_html: str | None = None
    answers_html: str | None = None

    @classmethod
    def from_state(cls, state: dict) -> "ExamForgeResponse":
        """파이프라인 최종 상태에서 응답 생성."""
        questions = [
            Question(**q)
            for q in state.get("calibrated_questions", [])
        ]
        plan = _coerce_exam_plan(state, len(questions))
        metrics = _coerce_quality_metrics(state)
        return cls(
            exam_id=state.get("exam_id", ""),
            exam_plan=ExamPlan(**plan),
            questions=questions,
            quality_metrics=QualityMetrics(**metrics),
            pipeline_outcome=state.get("pipeline_outcome", "passed"),
            answer_key_seal=state.get("answer_key_seal"),
            exam_html=state.get("output_html"),
            answers_html=state.get("answers_html"),
        )


def _coerce_exam_plan(state: dict, question_count: int) -> dict:
    """테스트 더블/부분 상태에서도 응답 스키마를 안정적으로 채운다."""
    # exam_plan 키 누락 시 빈 딕셔너리로 폴백해 KeyError 방지
    if state.get("exam_plan"):
        return state.get("exam_plan", {})

    config = state.get("exam_config", {})
    subject = state.get("subject") or config.get("subject") or "모의고사"
    total = config.get("total_questions", question_count)
    return {
        "exam_title": f"{subject} 모의고사",
        "subject": subject,
        "total_questions": total,
        "total_points": float(total),
        "time_limit_minutes": config.get("time_limit_minutes", 60),
        "locale": config.get("locale", state.get("locale", "ko")),
        "category": config.get("category", state.get("category", "korean")),
        "type_allocations": [],
        "topic_weights": {},
        "passing_score": config.get("passing_score", 60.0),
        "bloom_distribution": {},
    }


def _coerce_quality_metrics(state: dict) -> dict:
    """누락된 품질 지표를 보수적인 기본값으로 보완한다."""
    defaults = {
        "answer_accuracy_rate": 0.0,
        "dedup_score": 0.0,
        "coverage_score": 0.0,
        "distractor_plausibility_score": 0.0,
        "length_variance_ratio": 0.0,
        "bloom_distribution_actual": {},
        "retry_count": state.get("retry_count", 0),
        "generation_time_sec": 0.0,
    }
    return {**defaults, **state.get("quality_metrics", {})}
