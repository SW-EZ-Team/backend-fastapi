"""Anthropic API 기반 커넥터."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence

from anthropic import APIStatusError, AsyncAnthropic
from anthropic import RateLimitError as AnthropicRateLimitError

from app.modules.ExamForge_V1.common._ai_schemas import (
    AIConnector,
    ChapterAIRequest,
    ChapterAIResponse,
    LLMBudgetCounter,
    current_budget,
)
from app.modules.ExamForge_V1.common.config import claude_sonnet_api_key
from app.modules.ExamForge_V1.common.errors import ConnectorError, RateLimitError

# 재시도 설정
_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 5, 10]

# Anthropic 400 사용한도 소진 마커 — 일시적 400(잘못된 요청)과 구분한다.
# 실측: "You have reached your specified API usage limits. ... regain access on 2026-07-01"
# 이런 400은 같은 키라 재시도/재호출해도 복구일 전까지 전부 실패하므로,
# 비재시도 ConnectorError 로 올려 상위 폴백 래퍼가 다음 프로바이더로 즉시 넘기게 하고,
# 프로바이더 헬스 캐시에 소진을 passive 기록한다.
_ANTHROPIC_USAGE_LIMIT_MARKERS = (
    "usage limit",
    "usage limits",
    "regain access",
    "reached your specified api usage",
)


class AnthropicConnector:
    """Anthropic Claude API를 통해 텍스트를 생성하는 커넥터."""

    def __init__(self, model_id: str, connector_name: str) -> None:
        key = claude_sonnet_api_key()
        if not key:
            raise RuntimeError(
                f"{connector_name}: CLAUDE_SONNET_API_KEY 또는 ANTHROPIC_API_KEY 필요"
            )
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
            except AnthropicRateLimitError as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
            except APIStatusError as e:
                if e.status_code >= 500:
                    last_error = e
                    if attempt < _MAX_RETRIES - 1:
                        await asyncio.sleep(_RETRY_DELAYS[attempt])
                elif _is_usage_limit_error(e):
                    # 사용한도 소진 400 — 재시도/재호출 무의미. passive 기록 후
                    # 비재시도 ConnectorError 로 올려 상위 폴백이 즉시 다음 단계로 넘긴다.
                    message = str(e)
                    _record_provider_exhausted(self.name, message)
                    raise ConnectorError(
                        f"{self.name} 사용한도 소진 — 즉시 폴백: {message}"
                    ) from e
                else:
                    raise
            except asyncio.TimeoutError as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
        if isinstance(last_error, AnthropicRateLimitError):
            raise RateLimitError(f"API 호출 {_MAX_RETRIES}회 실패: {last_error}") from last_error
        raise ConnectorError(f"API 호출 {_MAX_RETRIES}회 실패: {last_error}") from last_error

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


def _is_usage_limit_error(exc: object) -> bool:
    """Anthropic 4xx 가 '사용한도 소진'(복구일 전까지 영구 실패)인지 메시지로 판별한다.

    일반 400(잘못된 요청)과 구분하기 위해 명시 마커가 있을 때만 True 다 —
    마커가 없으면 기존처럼 그대로 raise 되어 동작이 보존된다.
    """
    low = str(exc).lower()
    return any(marker in low for marker in _ANTHROPIC_USAGE_LIMIT_MARKERS)


def _record_provider_exhausted(provider: str, message: str) -> None:
    """프로바이더 헬스 캐시에 소진을 passive 기록한다(라이브 프로빙 아님).

    헬스 모듈 임포트/기록 실패가 생성 경로를 깨뜨리지 않도록 폭넓게 흡수한다.
    "regain access on <date>" 가 있으면 그 복구 시각까지 차단하고, 없으면 기본 TTL.
    """
    try:
        from app.modules.ExamForge_V1.common import _provider_health as health

        until = health.parse_regain_until(message)
        health.mark_exhausted(provider, reason=message[:200], until_monotonic=until)
    except Exception:  # noqa: BLE001 — 헬스 기록 실패가 생성 경로를 깨면 안 된다
        pass


def _extract_text(message: object) -> str:
    """응답 첫 텍스트 블록을 추출한다."""
    content = getattr(message, "content", ())
    if not isinstance(content, Sequence) or not content:
        return ""
    first = content[0]
    text = getattr(first, "text", None)
    return text if isinstance(text, str) else ""
