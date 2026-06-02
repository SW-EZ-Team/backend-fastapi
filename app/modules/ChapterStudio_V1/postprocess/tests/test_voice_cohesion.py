from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.postprocess.voice_cohesion import (
    apply_cohesion,
    detect_duplicate_openings,
    detect_greeting_openings,
)


def test_detect_greeting_openings_skips_first_slide() -> None:
    scripts = [
        (0, "안녕하세요. 오늘은 정수의 위치를 수직선 위에서 보겠습니다."),
        (1, "안녕하세요. 이제 0을 기준으로 방향을 나눠 봅시다."),
        (2, "반갑습니다. 음수와 양수의 이름을 확인해 봅니다."),
        (3, "이번에는 왼쪽과 오른쪽의 의미를 연결해 보겠습니다."),
        (4, "음수와 양수가 공존하는 정수의 세계에서 위치가 기준이 됩니다."),
        (5, "다들 안녕. 수직선 위 점을 직접 읽어 보겠습니다."),
        (6, "반가워요. 오른쪽으로 갈수록 수가 커집니다."),
        (7, "이 흐름을 이용해 두 정수를 비교해 봅니다."),
        (8, "음수와 양수가 공존하는 정수의 세계에서 기준점은 0입니다."),
        (9, "절댓값은 0에서 떨어진 거리로 생각합니다."),
        (10, "안녕 여러분, 마지막 확인 문제로 넘어가겠습니다."),
        (11, "음수와 양수가 공존하는 정수의 세계에서 복습을 시작합니다."),
    ]

    assert detect_greeting_openings(scripts) == [1, 2, 5, 6, 10]


def test_detect_duplicate_openings_returns_all_but_first() -> None:
    scripts = [
        (0, "수직선에서 0은 출발점입니다."),
        (4, "음수와 양수가 공존하는 정수의 세계에서 방향을 나눕니다."),
        (8, "음수와 양수가 공존하는 정수의 세계에서 기준을 확인합니다."),
        (11, "음수와 양수가 공존하는 정수의 세계에서 복습합니다."),
    ]

    assert detect_duplicate_openings(scripts) == [8, 11]


@pytest.mark.anyio
async def test_apply_cohesion_rewrites_only_target_intro_and_preserves_body() -> None:
    async def rewrite_fn(prompt: str) -> str:
        assert "topic=정수와 수직선" in prompt
        return "INTRO_FIXED."

    scripts = [
        (0, "안녕하세요. 첫 본문은 그대로 둡니다."),
        (1, "안녕하세요. 둘째 본문은 반드시 보존됩니다. 셋째 문장도 남습니다."),
        (2, "이번에는 다른 도입으로 자연스럽게 이어 갑니다. 본문입니다."),
    ]

    result = await apply_cohesion(scripts, "정수와 수직선", rewrite_fn)

    assert result[0][1] == scripts[0][1]
    assert result[1][1] == "INTRO_FIXED. 둘째 본문은 반드시 보존됩니다. 셋째 문장도 남습니다."
    assert result[2][1] == scripts[2][1]
