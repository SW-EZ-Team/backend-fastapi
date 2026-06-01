"""객관식 정답 위치 균등화 유틸리티."""
from __future__ import annotations


def balance_correct_answer_positions(questions: list[dict]) -> list[dict]:
    """같은 보기 수를 가진 객관식끼리 정답 인덱스를 고르게 재배치한다."""
    balanced = [q.copy() for q in questions]
    groups: dict[int, list[int]] = {}
    for index, question in enumerate(balanced):
        options = question.get("options")
        if _is_single_answer_mcq(options):
            groups.setdefault(len(options), []).append(index)
    for option_count, indexes in groups.items():
        targets = _balanced_targets(len(indexes), option_count)
        for group_pos, question_index in enumerate(indexes):
            balanced[question_index] = _move_correct_option(
                balanced[question_index],
                targets[group_pos],
            )
    return balanced


def answer_position_counts(questions: list[dict]) -> dict[int, int]:
    """객관식 정답 인덱스별 문항 수를 센다."""
    counts: dict[int, int] = {}
    for question in questions:
        options = question.get("options") or []
        for index, option in enumerate(options):
            if option.get("is_correct"):
                counts[index] = counts.get(index, 0) + 1
                break
    return counts


def _balanced_targets(question_count: int, option_count: int) -> list[int]:
    """0번부터 마지막 보기까지 가능한 한 같은 횟수로 배정한다."""
    return [index % option_count for index in range(question_count)]


def _is_single_answer_mcq(options: object) -> bool:
    """선택지가 있고 정답 표시가 정확히 하나인지 확인한다."""
    if not isinstance(options, list) or len(options) < 2:
        return False
    return sum(1 for option in options if option.get("is_correct")) == 1


def _move_correct_option(question: dict, target_index: int) -> dict:
    """정답 선택지를 목표 위치로 옮기고 label을 기존 순서 규칙에 맞춘다."""
    options = [option.copy() for option in question.get("options", [])]
    original_labels = [
        str(option.get("label", index + 1))
        for index, option in enumerate(options)
    ]
    current_index = next(
        index for index, option in enumerate(options)
        if option.get("is_correct")
    )
    correct_option = options.pop(current_index)
    options.insert(target_index, correct_option)
    for index, option in enumerate(options):
        option["label"] = original_labels[index]
    moved = question.copy()
    moved["options"] = options
    if moved.get("correct_answer"):
        moved["correct_answer"] = str(options[target_index].get("label", ""))
    return moved
