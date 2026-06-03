"""AI 커넥터 공통 스키마, 프로토콜, 예산 카운터 정의."""
from __future__ import annotations

import contextvars
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ExamForge_V1.common.config import pipeline_llm_budget
from app.modules.ExamForge_V1.common.errors import BudgetExceededError


class ChapterAIRequest(BaseModel):
    """AI 요청 스키마 - ChapterStudio_V1과 동일."""

    model_config = ConfigDict(strict=True, frozen=True)

    system: str = ""
    user: str = Field(min_length=1)
    max_tokens: int = Field(ge=1, le=32000)
    temperature: float = Field(ge=0.0, le=2.0)
    extra: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ChapterAIResponse(BaseModel):
    """AI 응답 스키마 - ChapterStudio_V1과 동일."""

    model_config = ConfigDict(strict=True, frozen=True)

    text: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    finish_reason: str


@runtime_checkable
class AIConnector(Protocol):
    """AI 커넥터 프로토콜."""

    name: str

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse: ...
    def supports(self, feature: str) -> bool: ...


class LLMBudgetCounter:
    """파이프라인 실행 단위로 공유되는 LLM 호출 카운터.

    budget을 초과하면 BudgetExceededError를 발생시켜
    재시도 증폭에 의한 비용 폭발(DoS)을 방지한다.

    [핵심 산출물 보호 — reserve]
    해설 생성(answer-gen)은 출고되는 모든 문항이 반드시 가져야 하는 필수 산출물이다.
    upstream 재시도(문제 생성·검증)가 예산을 모두 소진하면 정작 해설 생성이 굶어
    빈 해설로 출고되는 결함이 있었다. 이를 막기 위해 예산의 일부(reserve)를 떼어
    일반 호출(check/increment)에는 'budget - reserve'만 허용하고, 해설 생성은
    reserve 풀까지 끌어쓸 수 있게(allow_reserve=True) 한다.
    """

    def __init__(self, budget: int | None = None, reserve: int = 0) -> None:
        self._budget = budget if budget is not None else pipeline_llm_budget()
        # reserve는 전체 예산을 넘지 않도록 보정한다(음수·과대 방지).
        self._reserve = max(0, min(reserve, self._budget))
        self._count = 0

    @property
    def count(self) -> int:
        """현재까지 사용된 LLM 호출 횟수."""
        return self._count

    @property
    def budget(self) -> int:
        """설정된 예산 한도(reserve 포함 전체)."""
        return self._budget

    @property
    def reserve(self) -> int:
        """핵심 산출물(해설 생성) 전용으로 예약된 호출 수."""
        return self._reserve

    def _limit(self, allow_reserve: bool) -> int:
        """현재 호출이 사용할 수 있는 상한을 반환한다.

        allow_reserve=False(일반 호출): budget - reserve 까지만 허용.
        allow_reserve=True(해설 생성): 전체 budget 까지 허용.
        """
        return self._budget if allow_reserve else self._budget - self._reserve

    @property
    def exceeded(self) -> bool:
        """일반 호출 기준 예산 초과 여부(reserve 제외분 소진 여부).

        retry_router 서킷 브레이커가 참조한다. reserve를 제외한 일반 풀이
        소진되면 더 이상의 upstream 재시도를 막아 reserve를 해설 생성에 남긴다.
        """
        return self._count >= self._budget - self._reserve

    def _effective_allow_reserve(self, allow_reserve: bool | None) -> bool:
        """allow_reserve 인자가 None이면 contextvar(해설 생성 구간)에서 읽는다.

        모든 커넥터가 동일하게 reserve 보호를 받도록, 명시 인자가 없으면
        allow_reserve_budget 플래그를 자동 반영한다(커넥터별 중복 코드 방지).
        """
        if allow_reserve is not None:
            return allow_reserve
        return allow_reserve_budget.get()

    def increment(self, *, allow_reserve: bool | None = None) -> None:
        """호출 1회 카운트 증가. 예산 초과 시 예외 발생.

        allow_reserve가 True이거나 해설 생성 구간이면 reserve 풀까지 사용 가능.
        """
        effective = self._effective_allow_reserve(allow_reserve)
        self._count += 1
        if self._count > self._limit(effective):
            raise BudgetExceededError(
                f"LLM 호출 예산 초과: {self._count}/{self._limit(effective)}회"
                f"(전체 {self._budget}, 예약 {self._reserve}). "
                "파이프라인을 중단하고 부분 결과를 반환한다."
            )

    def check(self, *, allow_reserve: bool | None = None) -> None:
        """호출 전 예산 잔여 확인. 이미 초과 시 예외 발생.

        allow_reserve가 True이거나 해설 생성 구간이면 reserve 풀까지 사용 가능.
        """
        effective = self._effective_allow_reserve(allow_reserve)
        if self._count >= self._limit(effective):
            raise BudgetExceededError(
                f"LLM 호출 예산 소진: {self._count}/{self._limit(effective)}회"
                f"(전체 {self._budget}, 예약 {self._reserve}). "
                "추가 호출을 차단한다."
            )


# 파이프라인 실행 단위로 공유되는 예산 카운터 (contextvars로 요청 격리)
current_budget: contextvars.ContextVar[LLMBudgetCounter | None] = contextvars.ContextVar(
    "_current_budget", default=None
)

# 핵심 산출물(해설 생성) 구간 플래그.
# True인 동안 커넥터 호출은 예산 reserve 풀까지 끌어쓸 수 있다(allow_reserve).
# 해설 생성 노드가 진입/이탈 시 set/reset 해 upstream과 격리한다.
# _ai_schemas에 두는 이유: ai_bridge가 커넥터를 import하므로 순환 의존을 피하려면
# 커넥터가 참조하는 contextvar는 의존 그래프 하단(_ai_schemas)에 있어야 한다.
allow_reserve_budget: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_allow_reserve_budget", default=False
)
