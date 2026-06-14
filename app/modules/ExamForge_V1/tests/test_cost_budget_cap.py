"""비용 상한 강화 회귀 테스트.

배경: route_after_validation의 max_retries(기존 기본 3)로 풀 재생성이 최대 3회
반복되어 생성당 비용이 2~3배로 부풀었다. 이를 막기 위해:
  (1) max_retries 기본을 1로 낮춘다(env MOCK_EXAM_MAX_RETRIES로 조정).
  (2) LLMBudgetCounter에 시험당 하드 상한(max_calls)을 강제한다(env MOCK_EXAM_MAX_LLM_CALLS).
  (3) 생성 종료 시 [MockCost] 구조화 텔레메트리 로그를 남긴다.

검증 항목(라이브 호출 0 — mock/fixture·정적 호출만):
  (a) max_retries 기본이 1이다 + env로 조정 가능 + 기존 호환
  (b) budget 하드 상한 초과 시 BudgetExceededError가 발생하고(reserve 호출 포함),
      라우터 except가 잡아 graceful 종료(확보분 출고) 경로로 흐른다
  (c) [MockCost] 텔레메트리 로그가 요구 필드(attemptId/LLM호출/프로바이더/재시도/문항)를 포함한다
"""
from __future__ import annotations

import logging

import pytest

from app.modules.ExamForge_V1.common._ai_schemas import LLMBudgetCounter
from app.modules.ExamForge_V1.common.errors import BudgetExceededError


# ── (a) max_retries 기본 하향 ────────────────────────────────────────────────


def test_max_retries_default_is_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 미설정 시 max_retries 기본이 1이어야 한다(비용 최우선)."""
    from app.modules.ExamForge_V1.common import config

    # 두 env 모두 제거 — 순수 기본값 경로
    monkeypatch.delenv("MOCK_EXAM_MAX_RETRIES", raising=False)
    monkeypatch.delenv("MAX_RETRIES", raising=False)
    # _optional은 _load_env(@cache)를 거치지만 os.environ을 직접 읽으므로 monkeypatch가 반영된다
    assert config.max_retries() == 1


def test_max_retries_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """MOCK_EXAM_MAX_RETRIES로 재시도 횟수를 조정할 수 있다."""
    from app.modules.ExamForge_V1.common import config

    monkeypatch.setenv("MOCK_EXAM_MAX_RETRIES", "2")
    assert config.max_retries() == 2
    # 음수는 0으로 보정
    monkeypatch.setenv("MOCK_EXAM_MAX_RETRIES", "-5")
    assert config.max_retries() == 0


def test_max_retries_legacy_max_retries_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    """MOCK_EXAM_MAX_RETRIES 미설정 시 기존 MAX_RETRIES를 존중한다(기존 소비처 정합)."""
    from app.modules.ExamForge_V1.common import config

    monkeypatch.delenv("MOCK_EXAM_MAX_RETRIES", raising=False)
    monkeypatch.setenv("MAX_RETRIES", "3")
    assert config.max_retries() == 3


# ── (b) 시험당 LLM 호출 하드 상한 ─────────────────────────────────────────────


def test_max_calls_hard_cap_blocks_normal_calls() -> None:
    """일반 호출이 하드 상한(max_calls)에 도달하면 BudgetExceededError를 던진다."""
    # budget(100)은 크지만 하드 상한 3이 실효 천장이 된다.
    b = LLMBudgetCounter(budget=100, reserve=0, max_calls=3)
    for _ in range(3):
        b.increment(allow_reserve=False)
    assert b.count == 3
    with pytest.raises(BudgetExceededError):
        b.increment(allow_reserve=False)


def test_max_calls_hard_cap_blocks_reserve_calls() -> None:
    """reserve 호출(해설 생성)이라도 하드 상한은 넘지 못한다 — 비용 폭발 못박기."""
    # budget(100), reserve(50)이라도 max_calls=2가 절대 천장
    b = LLMBudgetCounter(budget=100, reserve=50, max_calls=2)
    b.increment(allow_reserve=True)
    b.increment(allow_reserve=True)
    assert b.count == 2
    # reserve 풀 여유와 무관하게 하드 상한 초과 차단
    with pytest.raises(BudgetExceededError):
        b.increment(allow_reserve=True)
    # check도 동일하게 차단
    with pytest.raises(BudgetExceededError):
        b.check(allow_reserve=True)


def test_max_calls_clamps_when_below_budget() -> None:
    """max_calls가 budget보다 작으면 실효 한도가 max_calls로 clamp된다."""
    b = LLMBudgetCounter(budget=80, reserve=10, max_calls=5)
    assert b.max_calls == 5
    for _ in range(5):
        b.increment()
    with pytest.raises(BudgetExceededError):
        b.check()


def test_max_calls_default_env_is_floor_not_below_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """env(MOCK_EXAM_MAX_LLM_CALLS)는 floor일 뿐, 예산 풀보다 낮게 cap을 깎지 못한다.

    (정책 변경 2026-06-13: 고정 env가 문항 비례 예산 풀보다 낮으면 정상 시험을
    끊던 회귀를 차단. env는 풀보다 클 때만 상향 천장 효과를 갖는다.)
    """
    import math
    from app.modules.ExamForge_V1.common import config
    from app.modules.ExamForge_V1.common._ai_schemas import _RUNAWAY_FACTOR

    # env가 풀보다 작으면(7) cap은 풀×factor로 유지 — env가 깎지 못한다
    monkeypatch.setenv("MOCK_EXAM_MAX_LLM_CALLS", "7")
    assert config.mock_exam_max_llm_calls() == 7
    b = LLMBudgetCounter(budget=200, reserve=0)  # max_calls 생략 → 기본 경로
    assert b.max_calls == math.ceil(200 * _RUNAWAY_FACTOR)  # 250, 7 아님

    # env가 풀×factor보다 크면 env가 상향 천장이 된다
    monkeypatch.setenv("MOCK_EXAM_MAX_LLM_CALLS", "500")
    b2 = LLMBudgetCounter(budget=200, reserve=0)
    assert b2.max_calls == 500


def test_max_calls_floor_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 이하 max_calls는 전면 차단 방지를 위해 최소 1로 보정한다."""
    b = LLMBudgetCounter(budget=50, reserve=0, max_calls=0)
    assert b.max_calls == 1
    b.increment()
    with pytest.raises(BudgetExceededError):
        b.increment()


def test_budget_exceeded_caught_by_router_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    """하드 상한 초과 시 라우터가 BudgetExceededError를 잡아 graceful 종료한다.

    _execute_exam_forge_pipeline은 그래프 ainvoke가 BudgetExceededError를 올리면
    RuntimeError로 감싸 상위(_run_async_generation)로 전달하고, 상위는 실패 콜백을
    보내며 예외를 외부로 전파하지 않는다(graceful). 여기서는 그래프를 가짜로 바꿔
    BudgetExceededError 경로가 실제로 RuntimeError로 graceful 변환되는지 확인한다.
    라이브 AI 호출은 발생하지 않는다(그래프 자체를 mock).
    """
    from app.modules.ExamForge_V1.app.routers import mock_async_router as mar
    from app.modules.ExamForge_V1.pipeline import graph as graph_mod

    class _BudgetBlowingGraph:
        async def ainvoke(self, _state: dict) -> dict:
            # 예산 하드 상한 초과를 모사 — 실제 LLM 호출 없음
            raise BudgetExceededError("LLM 호출 예산 초과(테스트 모사)")

    # get_compiled_graph는 _execute_exam_forge_pipeline 안에서 지연 임포트되므로
    # 원본 모듈(pipeline.graph)에 패치해야 한다.
    monkeypatch.setattr(graph_mod, "get_compiled_graph", lambda: _BudgetBlowingGraph())
    # DB 그라운딩 조회는 스텁 폴백으로 우회(라이브 의존 차단)
    monkeypatch.setattr(
        mar,
        "_load_grounded_source_text",
        _fake_grounded_source,
    )

    req = mar.MockGenerateAsyncRequest(
        attempt_id="att-budget-1",
        course_id="course-1",
        subject="자료구조",
        question_count=20,
    )

    import asyncio

    # _execute_exam_forge_pipeline은 BudgetExceededError를 RuntimeError로 감싸야 한다
    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(mar._execute_exam_forge_pipeline(req))
    assert "파이프라인 실행 실패" in str(exc_info.value)


def test_run_async_generation_graceful_on_budget_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """예산 초과로 파이프라인이 실패해도 _run_async_generation은 예외를 전파하지 않고
    실패 콜백을 보낸다(graceful 종료). 0건 출고가 아니라 실패 콜백 경로로 안전 종료."""
    from app.modules.ExamForge_V1.app.routers import mock_async_router as mar
    from app.modules.ExamForge_V1.pipeline import graph as graph_mod

    class _BudgetBlowingGraph:
        async def ainvoke(self, _state: dict) -> dict:
            raise BudgetExceededError("예산 초과(테스트 모사)")

    monkeypatch.setattr(graph_mod, "get_compiled_graph", lambda: _BudgetBlowingGraph())
    monkeypatch.setattr(mar, "_load_grounded_source_text", _fake_grounded_source)

    sent: dict = {}

    async def _capture_failed(attempt_id: str, reason: str) -> None:
        sent["attempt_id"] = attempt_id
        sent["reason"] = reason

    monkeypatch.setattr(mar, "_safe_send_failed_callback", _capture_failed)

    req = mar.MockGenerateAsyncRequest(
        attempt_id="att-budget-2",
        course_id="course-1",
        subject="운영체제",
        question_count=20,
    )

    import asyncio

    # 예외가 외부로 전파되지 않아야 한다(graceful)
    asyncio.run(mar._run_async_generation(req))
    assert sent.get("attempt_id") == "att-budget-2"
    assert "실패" in sent.get("reason", "") or "예산" in sent.get("reason", "")


# ── (c) 비용 텔레메트리 로그 ──────────────────────────────────────────────────


def test_mock_cost_telemetry_log_fields(caplog: pytest.LogCaptureFixture) -> None:
    """[MockCost] 로그가 요구 필드(attemptId/LLM호출/프로바이더/재시도/문항)를 포함한다."""
    from app.modules.ExamForge_V1.app.routers import mock_async_router as mar

    budget = LLMBudgetCounter(budget=64, reserve=8, max_calls=60)
    for _ in range(11):  # 누적 호출 11회 모사
        budget.increment()

    final_state = {
        "retry_count": 1,
        "calibrated_questions": [{"question_id": f"q{i}"} for i in range(18)],
    }

    with caplog.at_level(logging.INFO, logger=mar._LOG.name):
        mar._log_mock_cost("att-cost-1", budget, final_state)

    records = [r.getMessage() for r in caplog.records if "[MockCost]" in r.getMessage()]
    assert records, "MockCost 텔레메트리 로그가 한 건도 없다"
    msg = records[-1]
    assert "attemptId=att-cost-1" in msg
    assert "LLM호출=11" in msg
    assert "프로바이더=" in msg
    assert "재시도=1" in msg
    assert "문항=18" in msg


def test_mock_cost_telemetry_log_on_missing_state(caplog: pytest.LogCaptureFixture) -> None:
    """final_state가 None(예산 초과/타임아웃 등)이어도 텔레메트리가 안전하게 기록된다."""
    from app.modules.ExamForge_V1.app.routers import mock_async_router as mar

    budget = LLMBudgetCounter(budget=64, reserve=8, max_calls=60)
    budget.increment()

    with caplog.at_level(logging.INFO, logger=mar._LOG.name):
        mar._log_mock_cost("att-cost-2", budget, None)

    records = [r.getMessage() for r in caplog.records if "[MockCost]" in r.getMessage()]
    assert records
    msg = records[-1]
    assert "attemptId=att-cost-2" in msg
    assert "LLM호출=1" in msg
    # 재시도/문항은 상태 미상 시 안전 기본값(재시도=-1, 문항=0)
    assert "재시도=-1" in msg
    assert "문항=0" in msg


async def _fake_grounded_source(req: object) -> tuple[str, bool]:
    """DB 그라운딩 조회를 우회하는 스텁 — 라이브 의존 차단용."""
    return ("과목 기반 학습 자료 " * 20, False)


def test_default_max_calls_never_below_budget_pool() -> None:
    """[회귀] 명시하지 않은 기본 하드 상한은 예산 풀보다 낮게 clamp되지 않는다.

    고정 60이 20문항 비례 예산 풀(≈184)보다 낮아 정상 시험 1패스(≈81호출)도 끊던
    회귀를 차단. 라우터가 max_calls를 명시하지 않으므로 이 기본 경로가 실제 운영 경로다.
    """
    import math
    from app.modules.ExamForge_V1.common._ai_schemas import _RUNAWAY_FACTOR
    from app.modules.ExamForge_V1.common.config import pipeline_llm_budget_for

    pool = pipeline_llm_budget_for(20)  # 20문항 비례 예산
    b = LLMBudgetCounter(budget=pool, reserve=0)  # max_calls 미지정 = 운영 기본
    # 하드 상한이 예산 풀 이상이어야 정상 1패스(≈81)·보충까지 안 끊긴다
    assert b.max_calls >= pool
    assert b.max_calls >= math.ceil(pool * _RUNAWAY_FACTOR)
    # 20문항 단일 패스(약 81호출)는 절대 하드 상한에 안 걸린다
    assert b.max_calls > 81


def test_default_max_calls_blocks_runaway() -> None:
    """기본 하드 상한도 예산 풀을 크게 초과하는 폭주(예: 3배)는 막는다."""
    from app.modules.ExamForge_V1.common.config import pipeline_llm_budget_for
    pool = pipeline_llm_budget_for(20)
    b = LLMBudgetCounter(budget=pool, reserve=0)
    # 풀의 3배 수준 호출은 하드 상한에 걸린다
    assert b.max_calls < pool * 3
