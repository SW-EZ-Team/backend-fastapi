"""반복 붕괴(loop collapse) 감지 아톰 모듈.

page_03 에서 관찰된 「ふっん ふっん ...」 식 무한 반복 토큰 폭주를 조기에 차단한다.
생성 토큰 시퀀스를 줄 단위로 검사하고, 동일 패턴이 N회 이상 반복되면 True를 반환한다.
"""
from __future__ import annotations


# 반복 감지 임계값 — 같은 줄이 이 횟수 이상 반복되면 붕괴로 판정한다.
_LOOP_THRESHOLD = 6


def is_loop_collapse(text: str, threshold: int = _LOOP_THRESHOLD) -> bool:
    """생성된 텍스트에서 반복 붕괴 여부를 판정한다.

    줄 단위로 연속 중복을 카운트하고, 가장 많이 반복된 줄의 횟수가
    threshold 이상이면 True를 반환한다.
    빈 문자열이나 줄 수가 적은 경우는 즉시 False로 처리한다.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < threshold:
        return False
    # 연속 최대 반복 횟수를 계산한다 (비연속 반복은 무시).
    max_run = 1
    current_run = 1
    for i in range(1, len(lines)):
        if lines[i] == lines[i - 1]:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 1
    return max_run >= threshold
