"""Claude Sonnet 텍스트 생성 커넥터.

Anthropic SDK 를 감싸고 벤더 예외를 공통 예외 계층으로 번역한다.
generate_batch 는 semaphore 로 병렬 상한을 제어한다.
"""
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

from ai_connectors.errors import (
    AuthError,
    ConnectorError,
    ContextLengthExceeded,
    RateLimitError,
)
from ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from ai_connectors.text_schemas import ChapterAIRequest, ChapterAIResponse
from common.text_config import (
    claude_sonnet_api_key,
    claude_sonnet_max_concurrency,
    claude_sonnet_model,
    claude_sonnet_timeout_sec,
)


class ClaudeSonnetConnector:
    """Anthropic Claude Sonnet API 커넥터.

    벤더 SDK 예외를 ai_connectors.errors 예외로 정규화해 호출부가
    벤더를 알 필요 없도록 격리한다.
    """

    name = "claude_sonnet"

    def __init__(self) -> None:
        # API 키 미설정 시 생성 단계에서 즉시 실패 — 런타임 AuthError 방지
        api_key = claude_sonnet_api_key()
        if api_key is None:
            raise AuthError("CLAUDE_SONNET_API_KEY 또는 ANTHROPIC_API_KEY가 설정되지 않았다.")
        self._client = AsyncAnthropic(api_key=api_key, timeout=claude_sonnet_timeout_sec())
        self._model = claude_sonnet_model()

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """단일 요청을 Claude API 에 보내고 정규화된 응답을 반환한다."""
        try:
            msg = await self._client.messages.create(
                model=self._model,
                max_tokens=req.max_tokens,
                # Anthropic API 는 temperature 를 1.0 초과 허용하지 않음
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
        except (
            _AnthropicAPITimeoutError,
            _AnthropicAPIConnectionError,
            _AnthropicInternalServerError,
        ) as exc:
            raise ConnectorTimeoutError(str(exc)) from exc
        except _AnthropicBadRequestError as exc:
            msg_lower = str(exc).lower()
            if "context" in msg_lower or "too long" in msg_lower:
                raise ContextLengthExceeded(str(exc)) from exc
            raise ConnectorError(str(exc)) from exc

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        """병렬 상한(semaphore) 을 지키며 여러 요청을 동시에 처리한다."""
        if not reqs:
            return []
        semaphore = asyncio.Semaphore(claude_sonnet_max_concurrency())

        async def _guarded(req: ChapterAIRequest) -> ChapterAIResponse:
            async with semaphore:
                return await self.generate(req)

        return list(await asyncio.gather(*[_guarded(r) for r in reqs]))

    async def aclose(self) -> None:
        """AsyncAnthropic 클라이언트 연결을 정리한다."""
        await self._client.close()

    def supports(self, feature: str) -> bool:
        return feature in {"long_context", "json_mode", "batch", "fallback"}


# --- 순수 함수 헬퍼 (메시지 파싱) ---

def _first_text_block(message: object) -> str:
    """응답 content 첫 번째 text 블록을 추출한다."""
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
    """응답에서 (input_tokens, output_tokens) 쌍을 반환한다."""
    usage = getattr(message, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise ConnectorError("claude_sonnet: usage 토큰 정보가 올바르지 않다.")
    return input_tokens, output_tokens


def _stop_reason(message: object) -> str:
    """stop_reason 을 문자열로 반환한다. 없으면 'unknown'."""
    reason = getattr(message, "stop_reason", None)
    if isinstance(reason, str):
        return reason
    return "unknown"
