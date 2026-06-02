from __future__ import annotations

from collections import Counter

from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedQuiz
from app.modules.ChapterStudio_V1.postprocess.quiz_balance import (
    balance_quiz_answers,
    balanced_target_positions,
    strip_answer_position_reference,
    shuffle_quiz_choices,
)


def test_balanced_target_positions_evenly_distributes_twelve_items() -> None:
    positions_a = balanced_target_positions(12, seed=1)
    positions_b = balanced_target_positions(12, seed=2)

    assert Counter(positions_a) == {0: 3, 1: 3, 2: 3, 3: 3}
    assert Counter(positions_b) == {0: 3, 1: 3, 2: 3, 3: 3}
    assert positions_a != positions_b


def test_shuffle_quiz_choices_moves_answer_and_preserves_choice_multiset() -> None:
    choices = ["정답", "오답1", "오답2", "오답3"]

    shuffled, new_answer_idx = shuffle_quiz_choices(choices, answer_idx=0, target_idx=2)

    assert shuffled[2] == "정답"
    assert Counter(shuffled) == Counter(choices)
    assert new_answer_idx == 2
    assert shuffled == ["오답1", "오답2", "정답", "오답3"]


def test_strip_answer_position_reference_removes_intro_position_phrase() -> None:
    explanation = "정답은 2번이야. 출금은 돈이 계좌에서 나가는 상황이라 핵심 개념과 맞습니다."

    assert strip_answer_position_reference(explanation) == "출금은 돈이 계좌에서 나가는 상황이라 핵심 개념과 맞습니다."


def test_strip_answer_position_reference_keeps_explanation_without_position() -> None:
    explanation = "출금은 돈이 계좌에서 나가는 상황이라 핵심 개념과 맞습니다."

    assert strip_answer_position_reference(explanation) == explanation


def test_balance_quiz_answers_evenly_spreads_biased_demo_input() -> None:
    quizzes = [_quiz(idx, 0) for idx in range(9)] + [_quiz(idx, 1) for idx in range(9, 12)]
    before_answers = {quiz.slide_idx: quiz.choices[quiz.answer_idx] for quiz in quizzes}

    balanced = balance_quiz_answers(quizzes, seed_key="demo-lesson")
    counts = Counter(quiz.answer_idx for quiz in balanced)
    after_answers = {quiz.slide_idx: quiz.choices[quiz.answer_idx] for quiz in balanced}

    assert max(counts.values()) - min(counts.values()) <= 1
    assert counts == {0: 3, 1: 3, 2: 3, 3: 3}
    assert after_answers == before_answers
    for original, changed in zip(quizzes, balanced, strict=True):
        assert Counter(changed.choices) == Counter(original.choices)


def test_balance_quiz_answers_strips_intro_position_and_balances_all_demo_items() -> None:
    quizzes = [_quiz_with_position_intro(idx, idx % 4) for idx in range(12)]
    before_answers = {quiz.slide_idx: quiz.choices[quiz.answer_idx] for quiz in quizzes}

    balanced = balance_quiz_answers(quizzes, seed_key="qwen-demo-position-intro")
    counts = Counter(quiz.answer_idx for quiz in balanced)
    after_answers = {quiz.slide_idx: quiz.choices[quiz.answer_idx] for quiz in balanced}

    assert counts == {0: 3, 1: 3, 2: 3, 3: 3}
    assert after_answers == before_answers
    assert all("정답은" not in quiz.explanation for quiz in balanced)
    assert all("번이야" not in quiz.explanation for quiz in balanced)
    assert all(quiz.choices[quiz.answer_idx] == before_answers[quiz.slide_idx] for quiz in balanced)


def _quiz(slide_idx: int, answer_idx: int) -> GeneratedQuiz:
    choices = [f"{slide_idx}-보기-{idx}" for idx in range(4)]
    return GeneratedQuiz(
        slide_idx=slide_idx,
        question=f"{slide_idx}번 문항의 질문입니다.",
        choices=choices,
        answer_idx=answer_idx,
        difficulty="이해",
        explanation="정답 개념은 슬라이드의 핵심 정의와 직접 연결되며 오답은 조건을 빠뜨립니다.",
    )


def _quiz_with_position_intro(slide_idx: int, answer_idx: int) -> GeneratedQuiz:
    choices = [f"{slide_idx}-보기-{idx}" for idx in range(4)]
    return GeneratedQuiz(
        slide_idx=slide_idx,
        question=f"{slide_idx}번 문항의 질문입니다.",
        choices=choices,
        answer_idx=answer_idx,
        difficulty="이해",
        explanation=f"정답은 {answer_idx + 1}번이야. 핵심 선택지는 슬라이드 개념을 정확히 적용합니다.",
    )
