"""주제 커버리지 분석."""
from __future__ import annotations


def analyze_coverage(
    questions: list[dict],
    topic_weights: dict[str, float],
) -> tuple[float, list[str]]:
    """문제 목록이 계획된 주제를 얼마나 커버하는지 분석한다.

    Returns:
        (coverage_score, uncovered_topics)
        coverage_score: 0.0~1.0
    """
    if not topic_weights:
        return 1.0, []

    # 실제 주제별 문제 수 집계
    topic_counts: dict[str, int] = {}
    for q in questions:
        topic = q.get("topic", "")
        if topic:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

    total_questions = len(questions)
    covered_topics: set[str] = set()
    uncovered: list[str] = []
    weighted_coverage = 0.0

    for topic, weight in topic_weights.items():
        count = topic_counts.get(topic, 0)
        if count > 0:
            covered_topics.add(topic)
            # 실제 비율 vs 목표 비율
            actual_ratio = count / total_questions if total_questions else 0
            ratio_coverage = min(actual_ratio / weight, 1.0) if weight > 0 else 1.0
            weighted_coverage += weight * ratio_coverage
        else:
            uncovered.append(topic)

    # 목표에 없는 주제도 카운트 (보너스 없음)
    coverage_score = min(1.0, weighted_coverage)
    return coverage_score, uncovered


def compute_topic_distribution(
    questions: list[dict],
) -> dict[str, int]:
    """주제별 문제 수를 반환한다."""
    dist: dict[str, int] = {}
    for q in questions:
        topic = q.get("topic", "기타")
        dist[topic] = dist.get(topic, 0) + 1
    return dist
