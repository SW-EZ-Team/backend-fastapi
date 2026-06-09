from __future__ import annotations

import asyncio
from collections.abc import Sequence

from anthropic import AsyncAnthropic
from anthropic import (
    AuthenticationError as _AnthropicAuthError,
    RateLimitError as _AnthropicRateLimitError,
    BadRequestError as _AnthropicBadRequestError,
)

from app.modules.ChapterStudio_V1.ai_connectors.errors import AuthError, ConnectorError, ContextLengthExceeded, RateLimitError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.common.config import anthropic_api_key

_MODEL_ID = "claude-opus-4-6"


class Opus46Connector:
    name = "opus46"

    def __init__(self) -> None:
        # API 키 누락은 첫 요청이 아니라 커넥터 생성 단계에서 드러나게 한다.
        if anthropic_api_key() is None:
            raise AuthError("ANTHROPIC_API_KEY가 설정되지 않았다.")
        self._client = AsyncAnthropic()

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        try:
            # 스트리밍으로 응답을 수집 — 10분 이상 걸릴 수 있는 요청의 SDK 타임아웃 제약 우회
            async with self._client.messages.stream(
                model=_MODEL_ID,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                system=req.system or "",
                messages=[{"role": "user", "content": req.user}],
            ) as stream:
                msg = await stream.get_final_message()
            text = _first_text_block(msg)
            usage = _usage_pair(msg)
            return ChapterAIResponse(
                text=text,
                model=_MODEL_ID,
                input_tokens=usage[0],
                output_tokens=usage[1],
                finish_reason=_stop_reason(msg),
            )
        except _AnthropicAuthError as e:
            raise AuthError(str(e)) from e
        except _AnthropicRateLimitError as e:
            raise RateLimitError(str(e)) from e
        except _AnthropicBadRequestError as e:
            if "context" in str(e).lower() or "too long" in str(e).lower():
                raise ContextLengthExceeded(str(e)) from e
            raise ConnectorError(str(e)) from e

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        return list(await asyncio.gather(*[self.generate(r) for r in reqs]))

    def supports(self, feature: str) -> bool:
        return feature in {"long_context", "json_mode"}


def _first_text_block(message: object) -> str:
    content = getattr(message, "content", ())
    if not isinstance(content, Sequence) or not content:
        raise ConnectorError("opus46: 응답 content가 비어 있다.")
    first = content[0]
    block_type = getattr(first, "type", "text")
    text = getattr(first, "text", None)
    if block_type != "text" or not isinstance(text, str):
        raise ConnectorError("opus46: 응답 첫 블록이 text 타입 아님")
    return text


def _usage_pair(message: object) -> tuple[int, int]:
    usage = getattr(message, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise ConnectorError("opus46: usage 토큰 정보가 올바르지 않다.")
    return input_tokens, output_tokens


def _stop_reason(message: object) -> str:
    reason = getattr(message, "stop_reason", None)
    if isinstance(reason, str):
        return reason
    return "unknown"
