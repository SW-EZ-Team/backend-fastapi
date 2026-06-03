"""run_connector_tasks 병렬화 + concurrency 기본값 검증 테스트.

변경 사항:
  A. run_connector_tasks — batch 게이트 제거 후 항상 asyncio.gather 병렬 실행
  B. generation_concurrency 기본값 4→3, verification_concurrency 기본값 2→3
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from app.modules.ExamForge_V1.common.ai_bridge import (
    connector_supports_batch,
    run_connector_tasks,
)


class _FakeConnectorBatchFalse:
    """supports('batch')=False를 반환하는 더미 커넥터."""

    name = "fake_no_batch"

    def supports(self, feature: str) -> bool:
        return False

    async def generate(self, req: object) -> object:  # pragma: no cover
        return MagicMock(text="ok")


class _FakeConnectorBatchTrue:
    """supports('batch')=True를 반환하는 더미 커넥터."""

    name = "fake_batch"

    def supports(self, feature: str) -> bool:
        return feature == "batch"

    async def generate(self, req: object) -> object:  # pragma: no cover
        return MagicMock(text="ok")


@pytest.mark.asyncio
async def test_run_connector_tasks_always_parallel_even_when_batch_false() -> None:
    """batch=False 커넥터도 이제 병렬로 실행돼 직렬보다 빠른지 검증한다."""
    # 각 팩토리가 0.05초씩 걸린다고 가정 — 직렬이면 0.05*5=0.25초+, 병렬이면 ~0.05초
    task_delay = 0.05
    call_count = 5

    async def slow_factory() -> str:
        await asyncio.sleep(task_delay)
        return "result"

    connector = _FakeConnectorBatchFalse()
    assert connector_supports_batch(connector) is False  # 전제 확인

    start = time.monotonic()
    results = await run_connector_tasks(
        [slow_factory for _ in range(call_count)],
        connector,
    )
    elapsed = time.monotonic() - start

    # 병렬이면 약 task_delay * 1.5 이하여야 한다 (여유 50%)
    assert elapsed < task_delay * call_count * 0.5, (
        f"병렬화 실패: {elapsed:.3f}s >= {task_delay * call_count * 0.5:.3f}s(상한). "
        "직렬로 실행됐을 가능성이 있다."
    )
    assert results == ["result"] * call_count


@pytest.mark.asyncio
async def test_run_connector_tasks_result_order_preserved() -> None:
    """gather 결과가 입력 팩토리 순서대로 반환되는지 검증한다."""
    order: list[int] = []

    async def factory(i: int) -> int:
        # 역순으로 완료되도록 지연을 역배치한다
        await asyncio.sleep((10 - i) * 0.005)
        order.append(i)
        return i

    connector = _FakeConnectorBatchFalse()
    results = await run_connector_tasks(
        [lambda idx=i: factory(idx) for i in range(5)],
        connector,
    )
    # 결과 순서는 입력 순서여야 한다(완료 순서와 무관)
    assert results == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_run_connector_tasks_exceptions_captured_not_raised() -> None:
    """팩토리 예외가 raise되지 않고 리스트에 담기는지 검증한다."""

    async def good_factory() -> str:
        return "ok"

    async def bad_factory() -> str:
        raise ValueError("의도된 예외")

    connector = _FakeConnectorBatchFalse()
    results = await run_connector_tasks(
        [good_factory, bad_factory, good_factory],
        connector,
    )
    assert results[0] == "ok"
    assert isinstance(results[1], ValueError)
    assert results[2] == "ok"


def test_generation_concurrency_default_is_3() -> None:
    """generation_concurrency()의 하드코딩 기본값이 3인지 소스 레벨로 검증한다.

    .env 파일에 GENERATION_CONCURRENCY가 명시돼 있어도 기본값 자체(4→3 변경)를
    확인하기 위해 _int_env 직접 호출을 모킹해 env를 건너뛴다.
    """
    from unittest.mock import patch

    from app.modules.ExamForge_V1.common import config

    # _int_env가 기본값(두 번째 인자)을 그대로 반환하도록 모킹해 실제 기본값만 추출
    captured: list[int] = []

    original_int_env = config._int_env

    def capture_default(key: str, default: int) -> int:
        captured.append(default)
        return default

    with patch.object(config, "_int_env", side_effect=capture_default):
        config.generation_concurrency()

    # generation_concurrency() 내부 _int_env 호출 시 기본값이 3이어야 한다
    assert captured == [3], f"기본값이 3이어야 하는데 {captured}를 받았다."


def test_verification_concurrency_default_is_3() -> None:
    """verification_concurrency()의 하드코딩 기본값이 3인지 소스 레벨로 검증한다."""
    from unittest.mock import patch

    from app.modules.ExamForge_V1.common import config

    captured: list[int] = []

    def capture_default(key: str, default: int) -> int:
        captured.append(default)
        return default

    with patch.object(config, "_int_env", side_effect=capture_default):
        config.verification_concurrency()

    assert captured == [3], f"기본값이 3이어야 하는데 {captured}를 받았다."
