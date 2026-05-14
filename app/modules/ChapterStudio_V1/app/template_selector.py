from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateDecision:
    key: str
    score: int
    matched: tuple[str, ...]
    reason: str


def choose_template(topic: str, rules: dict[str, tuple[str, ...]]) -> TemplateDecision:
    """주제 문자열을 점수화해 가장 적합한 학습 템플릿을 고른다."""
    lowered = topic.lower()
    best = TemplateDecision("foundation_overview", 0, (), "일치 규칙 없음")
    for key, words in rules.items():
        matched = tuple(word for word in words if word in lowered)
        score = _score(key, matched, lowered)
        if score > best.score:
            best = TemplateDecision(key, score, matched, _reason(key, score, matched))
    return best


def _score(key: str, matched: tuple[str, ...], lowered: str) -> int:
    base = sum(_weight(word) for word in matched)
    if not matched:
        return 0
    if key == "person_profile" and _looks_like_person(lowered, matched):
        base += 3
    if key in {"concept_code", "algorithm_trace", "system_design"} and _has_technical_context(lowered):
        base += 2
    if key in {"statistics_inference", "data_analysis"} and _has_quant_context(lowered):
        base += 2
    return base


def _weight(word: str) -> int:
    if len(word) >= 5:
        return 4
    if len(word) >= 3:
        return 3
    return 2


def _looks_like_person(lowered: str, matched: tuple[str, ...]) -> bool:
    markers = ("학자", "작가", "철학자", "개발자", "인물", "로널드", "피셔", "뉴턴", "다윈", "튜링")
    return any(marker in lowered for marker in markers) or len(matched) >= 2


def _has_technical_context(lowered: str) -> bool:
    markers = ("api", "class", "함수", "코드", "서비스", "의존성", "fastapi", "python")
    return any(marker in lowered for marker in markers)


def _has_quant_context(lowered: str) -> bool:
    markers = ("p-value", "신뢰구간", "회귀", "표본", "분포", "확률", "통계")
    return any(marker in lowered for marker in markers)


def _reason(key: str, score: int, matched: tuple[str, ...]) -> str:
    terms = ", ".join(matched[:4])
    return f"{key} score={score}, matched={terms}"
