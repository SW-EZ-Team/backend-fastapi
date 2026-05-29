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
    """

    def __init__(self, budget: int | None = None) -> None:
        self._budget = budget if budget is not None else pipeline_llm_budget()
        self._count = 0

    @property
    def count(self) -> int:
        """현재까지 사용된 LLM 호출 횟수."""
        return self._count

    @property
    def budget(self) -> int:
        """설정된 예산 한도."""
        return self._budget

    @property
    def exceeded(self) -> bool:
        """예산 초과 여부."""
        return self._count >= self._budget

    def increment(self) -> None:
        """호출 1회 카운트 증가. 예산 초과 시 예외 발생."""
        self._count += 1
        if self._count > self._budget:
            raise BudgetExceededError(
                f"LLM 호출 예산 초과: {self._count}/{self._budget}회. "
                "파이프라인을 중단하고 부분 결과를 반환한다."
            )

    def check(self) -> None:
        """호출 전 예산 잔여 확인. 이미 초과 시 예외 발생."""
        if self._count >= self._budget:
            raise BudgetExceededError(
                f"LLM 호출 예산 소진: {self._count}/{self._budget}회. "
                "추가 호출을 차단한다."
            )


# 파이프라인 실행 단위로 공유되는 예산 카운터 (contextvars로 요청 격리)
current_budget: contextvars.ContextVar[LLMBudgetCounter | None] = contextvars.ContextVar(
    "_current_budget", default=None
)
