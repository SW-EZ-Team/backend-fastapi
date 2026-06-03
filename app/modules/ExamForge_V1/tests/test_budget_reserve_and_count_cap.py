"""P1 회귀 방지: 예산 reserve(해설 보호) + 개수 부족 비수렴 캡 테스트.

라이브에서 드러난 결함:
  - upstream 재시도가 PIPELINE_LLM_BUDGET를 소진 → 해설 생성 굶음(빈 해설 출고)
  - dedup이 매번 같은 중복을 드롭 → missing_count 비수렴 → 무한 재시도로 예산 폭발

검증 항목:
  1. LLMBudgetCounter reserve가 일반 호출을 budget-reserve로 제한한다
  2. allow_reserve 구간에서만 reserve 풀까지 사용 가능
  3. allow_reserve_budget contextvar가 자동 반영된다(인자 생략 시)
  4. pipeline_llm_budget_for/reserve_for가 문항 수에 비례한다
  5. 개수 부족 비수렴 시 route_after_validation이 passed로 빠진다(무한 재시도 방지)
  6. 진전(missing_count 감소) 시 stuck 카운터가 리셋된다
"""
from __future__ import annotations

import pytest

from app.modules.ExamForge_V1.common._ai_schemas import (
    LLMBudgetCounter,
    allow_reserve_budget,
)
from app.modules.ExamForge_V1.common.errors import BudgetExceededError


# ── 1·2. reserve 기본 동작 ────────────────────────────────────────────────────

def test_reserve_limits_normal_calls() -> None:
    """일반 호출(allow_reserve=False)은 budget - reserve 까지만 허용된다."""
    b = LLMBudgetCounter(budget=10, reserve=4)
    # 일반 호출 6회는 통과
    for _ in range(6):
        b.increment(allow_reserve=False)
    assert b.count == 6
    # 7번째 일반 호출은 차단
    with pytest.raises(BudgetExceededError):
        b.increment(allow_reserve=False)


def test_reserve_pool_usable_only_with_allow_reserve() -> None:
    """일반 풀 소진 후에도 allow_reserve=True면 reserve 풀까지 사용 가능하다."""
    b = LLMBudgetCounter(budget=10, reserve=4)
    for _ in range(6):
        b.increment(allow_reserve=False)
    # 일반 풀 소진(6/6) — 일반 check는 차단
    with pytest.raises(BudgetExceededError):
        b.check(allow_reserve=False)
    # 해설 생성(allow_reserve=True)은 reserve 풀까지 OK
    b.check(allow_reserve=True)
    for _ in range(4):
        b.increment(allow_reserve=True)
    assert b.count == 10
    # 전체 예산 초과는 reserve여도 차단
    with pytest.raises(BudgetExceededError):
        b.increment(allow_reserve=True)


def test_reserve_exceeded_property_reflects_general_pool() -> None:
    """exceeded는 일반 풀(budget-reserve) 소진 여부를 반영한다(retry 차단용)."""
    b = LLMBudgetCounter(budget=10, reserve=4)
    assert b.exceeded is False
    for _ in range(6):
        b.increment(allow_reserve=False)
    # 일반 풀 소진 → exceeded True (retry_router가 추가 재시도 차단)
    assert b.exceeded is True


# ── 3. contextvar 자동 반영 ───────────────────────────────────────────────────

def test_allow_reserve_contextvar_auto_applied() -> None:
    """allow_reserve 인자를 생략하면 allow_reserve_budget contextvar를 자동 반영한다."""
    b = LLMBudgetCounter(budget=8, reserve=3)
    for _ in range(5):
        b.increment()  # 인자 생략 → 기본 False → 일반 풀 5/5
    # 일반 풀 소진 — contextvar False면 차단
    with pytest.raises(BudgetExceededError):
        b.check()
    # contextvar True로 설정 → check 통과
    token = allow_reserve_budget.set(True)
    try:
        b.check()  # 인자 생략이지만 contextvar=True → 5/8 통과
        b.increment()
        assert b.count == 6
    finally:
        allow_reserve_budget.reset(token)


def test_explicit_allow_reserve_overrides_contextvar() -> None:
    """명시 allow_reserve 인자는 contextvar보다 우선한다."""
    b = LLMBudgetCounter(budget=8, reserve=3)
    for _ in range(5):
        b.increment(allow_reserve=False)
    token = allow_reserve_budget.set(True)
    try:
        # 명시 False는 contextvar True를 무시하고 일반 풀 기준으로 차단
        with pytest.raises(BudgetExceededError):
            b.check(allow_reserve=False)
    finally:
        allow_reserve_budget.reset(token)


# ── 4. 문항 수 비례 예산 ──────────────────────────────────────────────────────

def test_budget_scales_with_question_count() -> None:
    """pipeline_llm_budget_for가 문항 수에 비례해 증가한다."""
    from app.modules.ExamForge_V1.common.config import (
        pipeline_llm_budget_for,
        pipeline_llm_reserve_for,
    )
    b5 = pipeline_llm_budget_for(5)
    b10 = pipeline_llm_budget_for(10)
    b20 = pipeline_llm_budget_for(20)
    # 단조 증가
    assert b5 < b10 < b20
    # 5문항도 정상 동작(생성·오답·해설·검증 ≈ 4단계 × 재시도)에 충분한 여유
    assert b5 >= 50
    # reserve도 문항 수 비례
    assert pipeline_llm_reserve_for(10) > pipeline_llm_reserve_for(5)
    # reserve는 전체 예산 미만이어야 한다(일반 풀이 0이 되면 안 됨)
    assert pipeline_llm_reserve_for(10) < b10


# ── 5·6. 개수 부족 비수렴 캡 ──────────────────────────────────────────────────

def _base_state(missing_count: int, stuck: int, prev: int) -> dict:
    """route_after_validation에 넣을 최소 상태를 만든다."""
    return {
        "pipeline_status": "routing",
        "retry_count": 1,
        "max_retries": 3,
        "calibrated_questions": [{"draft_id": f"d{i}"} for i in range(3)],
        "failed_question_ids": [],
        "validation_report": {"missing_count": missing_count, "answer_accuracy_rate": 1.0},
        "count_stuck_rounds": stuck,
        "prev_missing_count": prev,
        "exam_plan": {},
    }


def test_count_non_converging_routes_to_passed() -> None:
    """개수 부족이 비수렴 캡(2)에 도달하면 무한 재시도 대신 passed로 빠진다."""
    from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import (
        route_after_validation,
    )
    # stuck=2 (캡 도달) — 더 재시도해도 dedup이 같은 중복 드롭하므로 passed
    state = _base_state(missing_count=2, stuck=2, prev=2)
    assert route_after_validation(state) == "passed"


def test_count_still_retries_below_cap() -> None:
    """비수렴 캡 미만이면 정상적으로 retry한다(진전 기회 부여)."""
    from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import (
        route_after_validation,
    )
    state = _base_state(missing_count=2, stuck=0, prev=3)
    # stuck=0 → 아직 캡 미달 → retry (retry_count 1 < max 3)
    assert route_after_validation(state) == "retry"


@pytest.mark.asyncio
async def test_track_count_progress_resets_on_improvement() -> None:
    """missing_count가 줄면 stuck 카운터가 0으로 리셋된다."""
    from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import (
        retry_router_node,
    )
    # 직전 missing=3, 현재 missing=2 → 진전 → stuck 리셋
    state = _base_state(missing_count=2, stuck=1, prev=3)
    result = await retry_router_node(state)
    assert result.get("count_stuck_rounds") == 0
    assert result.get("prev_missing_count") == 2


@pytest.mark.asyncio
async def test_track_count_progress_increments_when_stuck() -> None:
    """missing_count가 줄지 않으면 stuck 카운터가 증가한다."""
    from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import (
        retry_router_node,
    )
    # 직전 missing=2, 현재 missing=2 → 진전 없음 → stuck+1
    state = _base_state(missing_count=2, stuck=1, prev=2)
    result = await retry_router_node(state)
    assert result.get("count_stuck_rounds") == 2
