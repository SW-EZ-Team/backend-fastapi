"""Anthropic API 기반 커넥터."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence

from anthropic import AsyncAnthropic, RateLimitError, APIStatusError

from app.modules.ExamForge_V1.common._ai_schemas import (
    AIConnector,
    ChapterAIRequest,
    ChapterAIResponse,
    LLMBudgetCounter,
    current_budget,
)
from app.modules.ExamForge_V1.common.config import anthropic_api_key

# 재시도 설정
_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 5, 10]


class AnthropicConnector:
    """Anthropic Claude API를 통해 텍스트를 생성하는 커넥터."""

    def __init__(self, model_id: str, connector_name: str) -> None:
        key = anthropic_api_key()
        if not key:
            raise RuntimeError(f"{connector_name}: ANTHROPIC_API_KEY 필요")
        self._client = AsyncAnthropic(api_key=key)
        self._model = model_id
        self.name = connector_name

    async def generate(
        self,
        req: ChapterAIRequest,
        budget: LLMBudgetCounter | None = None,
    ) -> ChapterAIResponse:
        """단일 메시지를 생성한다 (재시도 포함)."""
        if budget is None:
            budget = current_budget.get()
        if budget is not None:
            budget.check()

        last_error: BaseException | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                result = await self._call_api(req)
                if budget is not None:
                    budget.increment()
                return result
            except RateLimitError as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
            except APIStatusError as e:
                if e.status_code >= 500:
                    last_error = e
                    if attempt < _MAX_RETRIES - 1:
                        await asyncio.sleep(_RETRY_DELAYS[attempt])
                else:
                    raise
            except asyncio.TimeoutError as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
        raise RuntimeError(f"API 호출 {_MAX_RETRIES}회 실패: {last_error}")

    async def _call_api(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """단일 Anthropic API 호출을 수행한다."""
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=req.max_tokens,
            temperature=min(req.temperature, 1.0),
            system=req.system or "",
            messages=[{"role": "user", "content": req.user}],
            timeout=60.0,
        )
        text = _extract_text(msg)
        if not text:
            raise ValueError("빈 응답")
        usage = getattr(msg, "usage", None)
        return ChapterAIResponse(
            text=text,
            model=self._model,
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
            finish_reason=getattr(msg, "stop_reason", "unknown") or "unknown",
        )

    def supports(self, feature: str) -> bool:
        """지원 기능 확인."""
        return feature in {"long_context", "json_mode"}


def _extract_text(message: object) -> str:
    """응답 첫 텍스트 블록을 추출한다."""
    content = getattr(message, "content", ())
    if not isinstance(content, Sequence) or not content:
        return ""
    first = content[0]
    text = getattr(first, "text", None)
    return text if isinstance(text, str) else ""
