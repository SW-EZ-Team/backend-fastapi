"""블룸 분류 난이도 채점."""
from __future__ import annotations

# 블룸 분류 단계별 난이도 매핑
BLOOM_TO_DIFFICULTY: dict[str, int] = {
    "기억": 1, "Remember": 1,
    "이해": 2, "Understand": 2,
    "적용": 3, "Apply": 3,
    "분석": 4, "Analyze": 4,
    "평가": 5, "Evaluate": 5,
    "창조": 5, "Create": 5,
}

BLOOM_LEVELS_KO = ["기억", "이해", "적용", "분석", "평가", "창조"]
BLOOM_LEVELS_EN = [
    "Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"
]


def score_bloom_distribution(
    questions: list[dict],
) -> dict[str, float]:
    """문제 목록의 블룸 분류 분포를 계산한다.

    Returns:
        {"기억": 0.2, "이해": 0.3, ...} 형태의 비율 딕셔너리
    """
    total = len(questions)
    if total == 0:
        return {}

    counts: dict[str, int] = {}
    for q in questions:
        bloom = q.get("bloom_level", "")
        if bloom:
            counts[bloom] = counts.get(bloom, 0) + 1

    return {k: v / total for k, v in counts.items()}


def suggest_difficulty(bloom_level: str) -> int:
    """블룸 분류에 기반한 권장 난이도를 반환한다."""
    return BLOOM_TO_DIFFICULTY.get(bloom_level, 3)


def check_distribution_balance(
    actual: dict[str, float],
    target: dict[str, float],
    tolerance: float = 0.15,
) -> list[str]:
    """목표 분포 대비 불균형을 검사한다.

    Returns:
        불균형 경고 목록
    """
    warnings: list[str] = []
    for level, target_ratio in target.items():
        actual_ratio = actual.get(level, 0.0)
        diff = abs(actual_ratio - target_ratio)
        if diff > tolerance:
            direction = "과다" if actual_ratio > target_ratio else "부족"
            warnings.append(
                f"{level}: {direction} (목표 {target_ratio:.0%}, "
                f"실제 {actual_ratio:.0%})"
            )
    return warnings
