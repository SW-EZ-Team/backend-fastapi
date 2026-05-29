"""ASR 결과 품질 휴리스틱 순수 함수 모음.

LangGraph, ASRConnector 등 어떤 커넥터 의존성도 없다.
텍스트 문자열 검사만 수행하므로 단위 테스트가 용이하다.
임계값은 config.py 에서 가져온다 (env override 지원).
"""
from __future__ import annotations

from .config import max_repeat_ngram, min_chars_per_sec, quality_pass_threshold


def score_empty(text: str) -> tuple[float, str]:
    """비어 있는 전사 결과 탐지.

    공백 제거 후 길이가 1자 이하이면 품질 0.0 / "empty" 를 반환한다.
    실제 내용이 있으면 1.0 / "ok" 를 반환한다.
    """
    stripped = text.strip()
    if len(stripped) < 2:
        return (0.0, "empty")
    return (1.0, "ok")


def score_char_rate(text: str, duration_sec: float) -> tuple[float, str]:
    """글자/초 비율로 전사 밀도를 검사한다.

    한국어 기준 chars/sec 가 min_chars_per_sec() 미만이면
    점수를 비율로 낮춘다 (0.3 미만은 "low_char_rate" 라벨).
    duration_sec 가 0 이면 안전하게 1.0 / "ok" 를 반환한다.
    """
    if duration_sec <= 0:
        return (1.0, "ok")
    threshold = min_chars_per_sec()
    char_len = len(text.strip())
    ratio = (char_len / duration_sec) / threshold
    # 비율을 0~1 로 클램핑
    clamped = max(0.0, min(1.0, ratio))
    label = "low_char_rate" if clamped < 0.3 else "ok"
    return (clamped, label)


def score_hallucination_loop(text: str) -> tuple[float, str]:
    """연속 n-gram 반복으로 할루시네이션을 탐지한다.

    단어 단위로 분리 후 3-word 슬라이딩 윈도우를 만들어
    동일 n-gram 이 max_repeat_ngram() 회 이상 등장하면
    0.0 / "hallucination_loop" 를 반환한다. 그 외 1.0 / "ok".
    """
    words = text.split()
    n = 3  # n-gram 크기 고정
    max_repeats = max_repeat_ngram()
    if len(words) < n:
        return (1.0, "ok")

    counts: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - n + 1):
        gram = tuple(words[i : i + n])
        counts[gram] = counts.get(gram, 0) + 1
        if counts[gram] >= max_repeats:
            return (0.0, "hallucination_loop")
    return (1.0, "ok")


def aggregate_quality(text: str, duration_sec: float) -> tuple[float, str]:
    """세 가지 휴리스틱 중 가장 낮은 점수를 종합 품질로 반환한다.

    반환값: (종합 점수, 이유 레이블)
    점수가 quality_pass_threshold() 이상이면 이유는 "acceptable" 로 덮어쓴다.
    """
    scores: list[tuple[float, str]] = [
        score_empty(text),
        score_char_rate(text, duration_sec),
        score_hallucination_loop(text),
    ]
    # 가장 낮은 점수를 선택 — 어느 하나라도 나쁘면 전체를 낮게 평가
    worst_score, worst_reason = min(scores, key=lambda t: t[0])
    if worst_score >= quality_pass_threshold():
        return (worst_score, "acceptable")
    return (worst_score, worst_reason)
