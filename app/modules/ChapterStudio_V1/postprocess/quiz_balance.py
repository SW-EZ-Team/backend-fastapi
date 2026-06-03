from __future__ import annotations

import re
from collections import Counter

from app.core.planfirst.positions import (
    balanced_target_positions,  # 단일 소스 위임 — core/planfirst/positions.py
    seed_from_key as _seed_from_key_impl,
)
from app.modules.ChapterStudio_V1.common.logging import logger
from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedQuiz

_POSITION_TOKEN_RE = re.compile(
    r"(?:보기|선택지|정답|오답)\s*(?:[A-Da-d]|[0-9]\s*번|[①②③④])"
    r"|(?:[A-Da-d])\s*(?:번|보기|선택지)"
    r"|(?:[0-9]\s*번|[①②③④])"
    r"|(?:첫|두|세|네)\s*번째\s*(?:보기|선택지)?"
)
_ANSWER_POSITION_PREFIX_RE = re.compile(
    r"^\s*(?:정답|답)\s*(?:은|는)?\s*[:：]?\s*"
    r"(?:[0-9]\s*번|[①②③④]|[A-Da-d]\s*(?:번|보기|선택지)?)"
    r"\s*(?:이야|입니다|이에요|이다|예요|야|임)?\s*"
    r"(?:[.。!！?？,:：;-]\s*|\s+)"
)


def strip_answer_position_reference(explanation: str) -> str:
    """해설 첫머리의 정답 위치 지칭만 제거하고 개념 설명은 보존한다."""
    stripped = _ANSWER_POSITION_PREFIX_RE.sub("", explanation, count=1).strip()
    return stripped if stripped else explanation


# balanced_target_positions는 app.core.planfirst.positions에서 re-export.
# 기존 호출처(balance_quiz_answers 등)는 이 이름으로 계속 사용 가능하다.
# 동작 무변경: byte-identical 알고리즘이 단일 소스로 통합됐다.


def shuffle_quiz_choices(
    choices: list[str], answer_idx: int, target_idx: int
) -> tuple[list[str], int]:
    """정답 선택지만 target_idx로 옮기고 나머지 보기의 상대 순서를 보존한다."""
    _validate_choice_args(choices, answer_idx, target_idx)
    if answer_idx == target_idx:
        return list(choices), target_idx
    answer = choices[answer_idx]
    remaining = [choice for idx, choice in enumerate(choices) if idx != answer_idx]
    shuffled = remaining[:target_idx] + [answer] + remaining[target_idx:]
    return shuffled, target_idx


def balance_quiz_answers(quizzes: list[GeneratedQuiz], seed_key: str = "") -> list[GeneratedQuiz]:
    """퀴즈 정답 위치를 결정적 셔플로 균등 분산한 새 퀴즈 목록을 반환한다."""
    if not quizzes:
        return []
    targets = balanced_target_positions(len(_eligible_quizzes(quizzes)), seed=_seed_from_key(seed_key))
    target_iter = iter(targets)
    balanced: list[GeneratedQuiz] = []
    for original in quizzes:
        quiz = _without_intro_position(original)
        if _has_position_token(quiz.explanation):
            _log_skip(original)
            balanced.append(original)
            continue
        target_idx = next(target_iter)
        choices, answer_idx = shuffle_quiz_choices(quiz.choices, quiz.answer_idx, target_idx)
        candidate = quiz.model_copy(update={"choices": choices, "answer_idx": answer_idx})
        if _has_position_token(candidate.explanation):
            _log_skip(original)
            balanced.append(original)
            continue
        balanced.append(candidate)
    _log_distribution(quizzes, balanced)
    return balanced


def _validate_choice_args(choices: list[str], answer_idx: int, target_idx: int) -> None:
    """선택지 길이와 인덱스 계약을 명시적으로 검증한다."""
    if len(choices) != 4:
        raise ValueError("choices는 정확히 4개여야 한다.")
    if answer_idx < 0 or answer_idx >= len(choices):
        raise ValueError("answer_idx가 choices 범위를 벗어났다.")
    if target_idx < 0 or target_idx >= len(choices):
        raise ValueError("target_idx가 choices 범위를 벗어났다.")


def _eligible_quizzes(quizzes: list[GeneratedQuiz]) -> list[GeneratedQuiz]:
    """도입 위치구 제거 뒤에도 위치 지칭이 없는 문항만 셔플 대상으로 고른다."""
    return [quiz for quiz in quizzes if not _has_position_token(strip_answer_position_reference(quiz.explanation))]


def _without_intro_position(quiz: GeneratedQuiz) -> GeneratedQuiz:
    """해설 도입부의 정답 위치 표현을 제거한 quiz를 만든다."""
    explanation = strip_answer_position_reference(quiz.explanation)
    if explanation == quiz.explanation:
        return quiz
    return quiz.model_copy(update={"explanation": explanation})


def _has_position_token(text: str) -> bool:
    """보기 위치를 직접 말하는 해설인지 감지한다."""
    return _POSITION_TOKEN_RE.search(text) is not None


def _seed_from_key(seed_key: str) -> int:
    """파이썬 해시 랜덤화에 영향받지 않는 고정 seed를 만든다.

    app.core.planfirst.positions.seed_from_key에 위임 — 동작 무변경.
    """
    return _seed_from_key_impl(seed_key)


def _log_skip(quiz: GeneratedQuiz) -> None:
    """위치 지칭 해설은 정합성 보존을 위해 셔플하지 않았음을 남긴다."""
    logger.warning("quiz_balance: slide_idx={} 해설 위치 지칭 감지 → 셔플 생략", quiz.slide_idx)


def _log_distribution(before: list[GeneratedQuiz], after: list[GeneratedQuiz]) -> None:
    """분산 전후 정답 위치 분포를 낮은 비용으로 남긴다."""
    before_counts = dict(sorted(Counter(quiz.answer_idx for quiz in before).items()))
    after_counts = dict(sorted(Counter(quiz.answer_idx for quiz in after).items()))
    logger.info("quiz_balance: answer_idx 분포 {} → {}", before_counts, after_counts)


__all__ = [
    "balance_quiz_answers",
    "balanced_target_positions",
    "strip_answer_position_reference",
    "shuffle_quiz_choices",
]
