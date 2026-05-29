from __future__ import annotations

import asyncio
from collections.abc import Sequence

from anthropic import APIConnectionError as _AnthropicAPIConnectionError
from anthropic import APITimeoutError as _AnthropicAPITimeoutError
from anthropic import AsyncAnthropic
from anthropic import AuthenticationError as _AnthropicAuthError
from anthropic import BadRequestError as _AnthropicBadRequestError
from anthropic import InternalServerError as _AnthropicInternalServerError
from anthropic import RateLimitError as _AnthropicRateLimitError

from app.modules.ChapterStudio_V1.ai_connectors.errors import AuthError, ConnectorError, ContextLengthExceeded, RateLimitError
from app.modules.ChapterStudio_V1.ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.common.config import (
    claude_sonnet_api_key,
    claude_sonnet_max_concurrency,
    claude_sonnet_model,
    claude_sonnet_timeout_sec,
)


class ClaudeSonnetConnector:
    name = "claude_sonnet"

    def __init__(self) -> None:
        api_key = claude_sonnet_api_key()
        if api_key is None:
            raise AuthError("CLAUDE_SONNET_API_KEY 또는 ANTHROPIC_API_KEY가 설정되지 않았다.")
        self._client = AsyncAnthropic(api_key=api_key, timeout=claude_sonnet_timeout_sec())
        self._model = claude_sonnet_model()

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        try:
            msg = await self._client.messages.create(
                model=self._model,
                max_tokens=req.max_tokens,
                temperature=min(req.temperature, 1.0),
                system=req.system or "",
                messages=[{"role": "user", "content": req.user}],
            )
            text = _first_text_block(msg)
            input_tokens, output_tokens = _usage_pair(msg)
            return ChapterAIResponse(
                text=text,
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=_stop_reason(msg),
            )
        except _AnthropicAuthError as exc:
            raise AuthError(str(exc)) from exc
        except _AnthropicRateLimitError as exc:
            raise RateLimitError(str(exc)) from exc
        except (_AnthropicAPITimeoutError, _AnthropicAPIConnectionError, _AnthropicInternalServerError) as exc:
            raise ConnectorTimeoutError(str(exc)) from exc
        except _AnthropicBadRequestError as exc:
            if "context" in str(exc).lower() or "too long" in str(exc).lower():
                raise ContextLengthExceeded(str(exc)) from exc
            raise ConnectorError(str(exc)) from exc

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        if not reqs:
            return []
        semaphore = asyncio.Semaphore(claude_sonnet_max_concurrency())

        async def guarded(req: ChapterAIRequest) -> ChapterAIResponse:
            async with semaphore:
                return await self.generate(req)

        return list(await asyncio.gather(*[guarded(req) for req in reqs]))

    async def aclose(self) -> None:
        await self._client.close()

    def supports(self, feature: str) -> bool:
        return feature in {"long_context", "json_mode", "batch", "fallback"}


def _first_text_block(message: object) -> str:
    content = getattr(message, "content", ())
    if not isinstance(content, Sequence) or not content:
        raise ConnectorError("claude_sonnet: 응답 content가 비어 있다.")
    first = content[0]
    block_type = getattr(first, "type", "text")
    text = getattr(first, "text", None)
    if block_type != "text" or not isinstance(text, str) or not text.strip():
        raise ConnectorError("claude_sonnet: 응답 첫 블록이 text 타입 아님")
    return text


def _usage_pair(message: object) -> tuple[int, int]:
    usage = getattr(message, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise ConnectorError("claude_sonnet: usage 토큰 정보가 올바르지 않다.")
    return input_tokens, output_tokens


def _stop_reason(message: object) -> str:
    reason = getattr(message, "stop_reason", None)
    if isinstance(reason, str):
        return reason
    return "unknown"
