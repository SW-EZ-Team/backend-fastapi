"""블룸 분류 난이도 채점."""
from __future__ import annotations

import re

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


# 정의 회상형 발문 패턴 — 난이도 4~5(분석/평가) 문항이 이 패턴이면 난이도 미달.
# "출력은 무엇인가" 같은 코드 추적 발문을 오탐하지 않도록 정의 문맥('란/정의')을 요구한다.
_RECALL_STEM_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(?:이?란)\s*무엇",                      # "소유권이란 무엇인가"
        r"의\s*정의(?:로|는|를|에|와)?",           # "클로저의 정의는?"
        r"정의로\s*(?:가장\s*)?(?:옳은|적절한)",   # "정의로 가장 적절한 것은"
        r"올바른\s*정의",                          # "올바른 정의를 고르시오"
        r"무엇을\s*(?:의미|뜻)하는\s*용어",        # "~을 의미하는 용어는"
        r"what\s+is\s+the\s+definition",
        r"\bis\s+defined\s+as\b",
    )
)

# 코드 추적 문항 식별 마커 — stem에 코드가 직접 들어간 경우 회상형 판정을 건너뛴다
_CODE_STEM_MARKERS: tuple[str, ...] = ("```", "fn ", "def ", "class ", "let ", "();", "{}")

# 회상형 판정을 적용하는 최소 난이도(블룸 분석 이상)
_HIGH_DIFFICULTY_FLOOR = 4


def check_difficulty_manifestation(question: dict) -> list[str]:
    """난이도 4 이상(분석/평가) 문항이 단순 정의 회상형 발문이면 결함으로 보고한다.

    계획이 상위 블룸 레벨을 배정해도 LLM이 "~란 무엇인가" 류의 회상 문항으로
    퇴화시키는 것을 결정론적으로 잡는다. 코드 스니펫 문항·코드 포함 발문은
    추적/분석 문항이므로 검사하지 않는다 (오탐 방지).

    Returns:
        결함 issue 리스트 — 비어 있으면 통과.
    """
    try:
        difficulty = int(question.get("difficulty", 0) or 0)
    except (ValueError, TypeError):
        return []
    if difficulty < _HIGH_DIFFICULTY_FLOOR:
        return []
    if question.get("code_snippet"):
        return []
    stem = str(question.get("stem", ""))
    if not stem.strip():
        return []
    if any(marker in stem for marker in _CODE_STEM_MARKERS):
        return []
    if any(pattern.search(stem) for pattern in _RECALL_STEM_PATTERNS):
        return [
            f"난이도 {difficulty}(분석/평가) 문항이 정의 회상형 발문 — "
            "두 개념 비교·코드/동작 추적·엣지케이스 분석을 요구하는 다단계 추론 발문으로 교정 필요"
        ]
    return []


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
