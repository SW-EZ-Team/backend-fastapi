"""2026-06-13 비용통제 정밀 감사에서 확정된 결함 3건의 회귀 테스트.

[1] Qwen27B Modal 어댑터가 다른 커넥터와 동일한 예산 계약을 따르는지(우회 차단)
[3] OpenAI 영구소진 마커가 일시 'billing' 오류를 오분류하지 않는지(false-positive)
[5] parse_source 가 AI의 쓰레기 chapter 라벨을 신뢰하지 않고 폴백하는지
모두 라이브 AI 호출 0 — 스텁/순수함수만 사용한다.
"""
from __future__ import annotations

import pytest

from app.modules.ExamForge_V1.common._ai_schemas import (
    ChapterAIRequest,
    LLMBudgetCounter,
    current_budget,
)
from app.modules.ExamForge_V1.common.errors import BudgetExceededError


# ---------------------------------------------------------------------------
# [1] Qwen27B Modal 어댑터 — 예산 카운터 우회 차단
# ---------------------------------------------------------------------------
class _FakeStudioResp:
    """ChapterStudio 응답 형태 스텁(.text/.model/토큰/finish_reason)."""

    text = "ok"
    model = "qwen27b-modal-stub"
    input_tokens = 1
    output_tokens = 1
    finish_reason = "stop"


class _FakeStudioConnector:
    """내부 Modal 커넥터 스텁 — 라이브 호출 없이 고정 응답만 돌려준다."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, _req):  # noqa: ANN001 - 스텁
        self.calls += 1
        return _FakeStudioResp()

    def supports(self, _feature: str) -> bool:
        return False


def _make_qwen_adapter() -> object:
    """실제 Modal 의존 없이 어댑터를 만들어 내부 커넥터만 스텁으로 교체한다."""
    from app.modules.ExamForge_V1.common.ai_bridge import _Qwen27BModalExamForgeAdapter

    adapter = object.__new__(_Qwen27BModalExamForgeAdapter)
    adapter._connector = _FakeStudioConnector()  # type: ignore[attr-defined]
    return adapter


def _req() -> ChapterAIRequest:
    return ChapterAIRequest(system="s", user="u", max_tokens=10, temperature=0.0)


@pytest.mark.asyncio
async def test_qwen_adapter_increments_budget_via_argument() -> None:
    """budget 인자를 직접 주면 호출마다 increment 되어야 한다."""
    adapter = _make_qwen_adapter()
    budget = LLMBudgetCounter(budget=5, reserve=0)
    await adapter.generate(_req(), budget)
    await adapter.generate(_req(), budget)
    assert budget.count == 2


@pytest.mark.asyncio
async def test_qwen_adapter_reads_contextvar_budget() -> None:
    """budget 인자가 없으면 current_budget contextvar에서 읽어 카운트한다."""
    adapter = _make_qwen_adapter()
    budget = LLMBudgetCounter(budget=5, reserve=0)
    token = current_budget.set(budget)
    try:
        await adapter.generate(_req())
        assert budget.count == 1
    finally:
        current_budget.reset(token)


@pytest.mark.asyncio
async def test_qwen_adapter_enforces_hard_cap() -> None:
    """예산이 소진되면 check()가 BudgetExceededError를 던져 우회가 불가능하다."""
    adapter = _make_qwen_adapter()
    budget = LLMBudgetCounter(budget=1, reserve=0, max_calls=1)
    await adapter.generate(_req(), budget)  # 1회 소진
    with pytest.raises(BudgetExceededError):
        await adapter.generate(_req(), budget)  # 2회차는 사전 check에서 차단


@pytest.mark.asyncio
async def test_qwen_adapter_no_budget_is_graceful() -> None:
    """budget 미설정(contextvar None)에서도 예외 없이 동작한다(테스트/독립 호출)."""
    adapter = _make_qwen_adapter()
    resp = await adapter.generate(_req())
    assert resp.text == "ok"


# ---------------------------------------------------------------------------
# [3] OpenAI 영구소진 마커 — 일시 'billing' 오류 오분류 방지
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "message",
    [
        "Error code 429: insufficient_quota",
        "You exceeded your current quota, please check your plan and billing details",
        "billing_hard_limit_reached",
        "billing_not_active",
    ],
)
def test_openai_permanent_quota_is_exhausted(message: str) -> None:
    from app.modules.ExamForge_V1.common._connector_openai import _is_billing_exhausted

    assert _is_billing_exhausted(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "Temporarily unable to reach billing system, retry later",  # 일시 + 'billing' 포함
        "We are updating our billing infrastructure",
        "Rate limit reached for requests per minute",
        "The server had an error processing your request",
    ],
)
def test_openai_transient_billing_is_not_exhausted(message: str) -> None:
    """메시지에 'billing'이 들어 있어도 일시 오류는 영구 소진으로 보지 않는다."""
    from app.modules.ExamForge_V1.common._connector_openai import _is_billing_exhausted

    assert _is_billing_exhausted(message) is False


# ---------------------------------------------------------------------------
# [5] parse_source — 쓰레기 chapter 라벨 거부 후 폴백
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "label,expected",
    [
        ("스프링 부트", True),
        ("DI", True),
        ("", False),
        (" ", False),
        ("\n", False),
        ("A", False),  # 단일 문자
        ("[chapter]", False),  # 구조 토큰 시작
        ("{json}", False),
        ("# 헤딩마커", False),
    ],
)
def test_is_valid_chapter_label(label: str, expected: bool) -> None:
    from app.modules.ExamForge_V1.pipeline.nodes.parse_source_node import (
        _is_valid_chapter_label,
    )

    assert _is_valid_chapter_label(label.strip()) is expected


def test_ensure_topic_chapters_rejects_garbage_and_falls_back() -> None:
    """AI가 준 공백/구조토큰 chapter는 버리고 헤딩/name으로 다시 도출한다."""
    from app.modules.ExamForge_V1.pipeline.nodes.parse_source_node import (
        _ensure_topic_chapters,
    )

    topics = [
        {"name": "의존성 주입", "chapter": "\n"},      # 쓰레기 → name 폴백
        {"name": "AOP", "chapter": "[unfinished"},      # 구조토큰 → name 폴백
        {"name": "빈 생명주기", "chapter": "스프링 컨테이너"},  # 유효 → 존중
    ]
    result = _ensure_topic_chapters(topics, "## 스프링 핵심 원리")
    assert result[0]["chapter"] == "의존성 주입"
    assert result[1]["chapter"] == "AOP"
    assert result[2]["chapter"] == "스프링 컨테이너"
