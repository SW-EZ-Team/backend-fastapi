"""품질 메트릭 통합 계산."""
from __future__ import annotations

import math

from app.modules.ExamForge_V1.common.verification_status import (
    is_genuine_fail,
    is_parse_failed,
    is_verified_pass,
)
from .deduplicator import check_duplicates
from .difficulty_scorer import score_bloom_distribution
from .coverage_analyzer import analyze_coverage


def compute_quality_metrics(
    questions: list[dict],
    topic_weights: dict[str, float],
    verification_results: list[dict],
    generation_time_sec: float,
    retry_count: int,
) -> dict:
    """모든 품질 지표를 계산하여 딕셔너리로 반환한다."""
    accuracy_rate, verification_summary = _verification_accuracy(verification_results)

    # 중복 점수
    dedup_score, _ = check_duplicates(questions)

    # 커버리지 점수
    coverage_score, _ = analyze_coverage(questions, topic_weights)

    # 오답 그럴듯함: 0~5점 척도의 DPS 점수
    dps = _compute_distractor_plausibility(questions)

    # 문제 줄기 길이 분산 비율 (LVR)
    lvr = _compute_length_variance_ratio(questions)

    # 블룸 분포
    bloom_dist = score_bloom_distribution(questions)

    return {
        "answer_accuracy_rate": round(accuracy_rate, 3),
        "answer_verification_parse_failed_count": verification_summary["parse_failed"],
        "answer_verification_parse_failed_ratio": round(verification_summary["parse_failed_ratio"], 3),
        "answer_verification_evaluable_count": verification_summary["evaluable"],
        "dedup_score": round(dedup_score, 3),
        "coverage_score": round(coverage_score, 3),
        "distractor_plausibility_score": round(dps, 3),
        "length_variance_ratio": round(lvr, 3),
        "bloom_distribution_actual": bloom_dist,
        "retry_count": retry_count,
        "generation_time_sec": round(generation_time_sec, 2),
    }


def _verification_accuracy(verification_results: list[dict]) -> tuple[float, dict[str, int | float]]:
    """parse_failed를 정답 실패율에서 제외하고 별도 지표로 집계한다."""
    summary: dict[str, int | float] = {
        "passed": 0,
        "failed": 0,
        "parse_failed": 0,
        "evaluable": 0,
        "parse_failed_ratio": 0.0,
    }
    for result in verification_results:
        if is_parse_failed(result):
            summary["parse_failed"] += 1
            continue
        if is_verified_pass(result):
            summary["passed"] += 1
            summary["evaluable"] += 1
            continue
        if is_genuine_fail(result):
            summary["failed"] += 1
            summary["evaluable"] += 1
    total = len(verification_results)
    summary["parse_failed_ratio"] = summary["parse_failed"] / total if total else 0.0
    if summary["evaluable"]:
        return summary["passed"] / summary["evaluable"], summary
    if total and summary["parse_failed"] == total:
        return 1.0, summary
    return 0.0, summary


def _compute_distractor_plausibility(questions: list[dict]) -> float:
    """객관식 문제의 오답 그럴듯함을 0~5점 척도(DPS)로 계산한다.

    점수 구성:
      - 길이 균일도 (최대 2.0점): 보기 텍스트 길이의 CV로 산출
      - 복잡도 균일도 (최대 1.5점): 보기별 단어 수의 CV로 산출
      - 보기 수 페널티 (최대 1.5점): 4개 이상이면 만점, 미만이면 0.5점 감점
    객관식 문제가 없으면 허용 가능한 기본값인 3.5를 반환한다.
    """
    scores: list[float] = []

    for q in questions:
        options = q.get("options")
        if not options or len(options) < 2:
            # 객관식이 아닌 문제는 건너뜀
            continue

        texts = [o.get("text", "") for o in options]

        # --- 길이 균일도 (최대 2.0점) ---
        lengths = [len(t) for t in texts]
        length_score = _uniformity_score(lengths, max_points=2.0)

        # --- 복잡도 균일도: 단어 수 기반 (최대 1.5점) ---
        word_counts = [len(t.split()) for t in texts]
        complexity_score = _uniformity_score(word_counts, max_points=1.5)

        # --- 보기 수 페널티 (최대 1.5점) ---
        # 4개 이상이면 만점, 미만이면 0.5점 감점
        option_score = 1.5 if len(options) >= 4 else 1.0

        scores.append(length_score + complexity_score + option_score)

    if not scores:
        # 객관식 문제가 없는 시험지는 허용 가능 기본값 반환
        return 3.5
    return sum(scores) / len(scores)


def _uniformity_score(values: list[int | float], max_points: float) -> float:
    """값 목록의 변동계수(CV)를 이용해 균일도 점수를 반환한다.

    CV가 낮을수록(균일할수록) max_points에 가까운 점수를 반환한다.
    """
    if not values:
        return 0.0
    mean_val = sum(values) / len(values)
    if mean_val == 0:
        # 평균이 0이면 모든 값이 0이므로 완전 균일로 처리
        return max_points
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
    cv = math.sqrt(variance) / mean_val
    # CV=0 -> 만점, CV 증가 시 점수 감소
    return max_points / (1.0 + cv)


def _compute_length_variance_ratio(questions: list[dict]) -> float:
    """문제 줄기 길이의 분산 비율(LVR)을 계산한다.

    LVR = std(줄기 길이) / mean(줄기 길이)
    - LVR < 0.1: 너무 균일 (쿠키커터 생성 의심)
    - LVR > 0.5: 너무 다양 (품질 일관성 저하 의심)
    - 0.1 ~ 0.5: 건강한 분산
    문제가 1개 이하이거나 평균 줄기 길이가 0이면 0.0을 반환한다.
    """
    stems = [len(q.get("stem", q.get("question", ""))) for q in questions]
    if len(stems) < 2:
        return 0.0
    mean_len = sum(stems) / len(stems)
    if mean_len == 0:
        return 0.0
    variance = sum((s - mean_len) ** 2 for s in stems) / len(stems)
    return math.sqrt(variance) / mean_len
