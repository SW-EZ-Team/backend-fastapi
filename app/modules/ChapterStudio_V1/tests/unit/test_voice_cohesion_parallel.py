"""voice_cohesion.rewrite_openings 병렬화 검증 테스트.

변경 사항:
  D. rewrite_openings의 for-loop 직렬을 asyncio.gather 병렬로 전환.
     semaphore 파라미터 추가(None이면 unbounded).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.modules.ChapterStudio_V1.postprocess.voice_cohesion import rewrite_openings


@pytest.mark.anyio
async def test_rewrite_openings_runs_in_parallel() -> None:
    """여러 슬라이드 재작성이 병렬로 실행돼 직렬보다 빠른지 검증한다."""
    task_delay = 0.05
    target_idxs = [1, 2, 3, 4]  # 4개 슬라이드 교정
    scripts = [(idx, f"안녕하세요. 슬라이드 {idx} 본문입니다.") for idx in range(5)]
    topic = "테스트 토픽"

    async def slow_rewrite(prompt: str) -> str:
        await asyncio.sleep(task_delay)
        return "교정된 도입 문장"

    start = time.monotonic()
    result = await rewrite_openings(scripts, target_idxs, topic, slow_rewrite)
    elapsed = time.monotonic() - start

    # 병렬이면 약 task_delay * 1.5 이하여야 한다 (여유 50%)
    assert elapsed < task_delay * len(target_idxs) * 0.5, (
        f"병렬화 실패: {elapsed:.3f}s >= {task_delay * len(target_idxs) * 0.5:.3f}s(상한). "
        "직렬로 실행됐을 가능성이 있다."
    )
    assert set(result.keys()) == set(target_idxs)
    for idx in target_idxs:
        assert result[idx].startswith("교정된 도입 문장")


@pytest.mark.anyio
async def test_rewrite_openings_semaphore_caps_concurrency() -> None:
    """세마포어가 주입되면 동시 실행을 제한하는지 검증한다."""
    concurrent_peak = 0
    concurrent_now = 0

    semaphore = asyncio.Semaphore(2)  # 동시 2개로 제한
    scripts = [(idx, f"안녕하세요. 슬라이드 {idx} 본문.") for idx in range(6)]
    target_idxs = [1, 2, 3, 4, 5]
    topic = "세마포어 테스트"

    async def tracking_rewrite(prompt: str) -> str:
        nonlocal concurrent_peak, concurrent_now
        concurrent_now += 1
        concurrent_peak = max(concurrent_peak, concurrent_now)
        await asyncio.sleep(0.02)
        concurrent_now -= 1
        return "교정됨"

    await rewrite_openings(scripts, target_idxs, topic, tracking_rewrite, semaphore=semaphore)

    # 세마포어 2 → 최대 동시 2 초과하면 안 됨
    assert concurrent_peak <= 2, f"동시 실행 {concurrent_peak}개가 세마포어(2) 초과"


@pytest.mark.anyio
async def test_rewrite_openings_no_semaphore_returns_correct_mapping() -> None:
    """세마포어 없이 호출해도 결과 매핑이 올바른지 확인한다."""
    scripts = [(i, f"안녕하세요. 슬라이드 {i} 본문.") for i in range(4)]
    target_idxs = [1, 2]
    topic = "기본 테스트"

    async def rewrite(prompt: str) -> str:
        return "새 도입부"

    result = await rewrite_openings(scripts, target_idxs, topic, rewrite)
    assert 1 in result
    assert 2 in result
    assert 0 not in result
    assert result[1].startswith("새 도입부")
    assert result[2].startswith("새 도입부")
