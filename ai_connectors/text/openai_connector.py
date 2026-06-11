"""OpenAI GPT 텍스트 폴백 커넥터.

Gemini 텍스트 커넥터(gemini_connector.py)와 동일한 공개 인터페이스
(generate / generate_batch / supports)를 제공한다. Gemini 장애 시 FailoverAIConnector
가 이 커넥터로 회로를 넘긴다. ClaudeSonnetConnector 처럼 AsyncOpenAI 를 직접 await 해
블로킹 스레드 래핑 없이 비동기로 동작한다.
"""
from __future__ import annotations

import asyncio
from collections.abc import Sequence

from openai import APIConnectionError as _OpenAIAPIConnectionError
from openai import APIError as _OpenAIAPIError
from openai import APITimeoutError as _OpenAIAPITimeoutError
from openai import AsyncOpenAI
from openai import AuthenticationError as _OpenAIAuthError
from openai import BadRequestError as _OpenAIBadRequestError
from openai import InternalServerError as _OpenAIInternalServerError
from openai import RateLimitError as _OpenAIRateLimitError

from ai_connectors.errors import (
    AuthError,
    ConnectorError,
    ContextLengthExceeded,
    RateLimitError,
)
from ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from ai_connectors.text_schemas import ChapterAIRequest, ChapterAIResponse
from common.text_config import openai_api_key, openai_text_model

try:
    from common.llm_output import strip_thinking as _strip_thinking
except ImportError:

    def _strip_thinking(text: str) -> str:
        """공통 정규화 모듈이 없으면 원문을 그대로 반환한다."""
        return text


# Gemini 커넥터의 배치 동시성 정책(단일 호출 gather)을 그대로 따른다.


class OpenAIConnector:
    """OpenAI GPT 텍스트 생성 커넥터(Gemini 폴백)."""

    name = "openai_text"

    def __init__(self) -> None:
        # API 키 미설정 시 생성 단계에서 즉시 실패 — 런타임 AuthError 방지
        api_key = openai_api_key()
        if api_key is None:
            raise AuthError("OPENAI_API_KEY 가 설정되지 않았다.")
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = openai_text_model()

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """단일 요청을 chat.completions 에 보내고 정규화된 응답을 반환한다.

        ChapterAIRequest 의 system/user/temperature/max_tokens 를 Gemini 커넥터와
        동일하게 매핑한다(system → system role, user → user role).
        """
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                messages=_build_messages(req),
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            )
        except _OpenAIAuthError as exc:
            raise AuthError(str(exc)) from exc
        except _OpenAIRateLimitError as exc:
            raise RateLimitError(str(exc)) from exc
        except (
            _OpenAIAPITimeoutError,
            _OpenAIAPIConnectionError,
            _OpenAIInternalServerError,
        ) as exc:
            raise ConnectorTimeoutError(str(exc)) from exc
        except _OpenAIBadRequestError as exc:
            raise _map_bad_request(exc) from exc
        except _OpenAIAPIError as exc:
            raise ConnectorError(str(exc)) from exc
        return _to_response(completion, req, self._model)

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        """호환성용 배치 처리. 모델 자체 배치가 아니라 단일 호출 gather다."""
        return list(await asyncio.gather(*[self.generate(req) for req in reqs]))

    async def aclose(self) -> None:
        """AsyncOpenAI 클라이언트 연결을 정리한다."""
        await self._client.close()

    def supports(self, feature: str) -> bool:
        return feature in {"long_context", "json_mode", "fallback", "openai"}


def _build_messages(req: ChapterAIRequest) -> list[dict[str, str]]:
    """ChapterAIRequest 를 chat.completions messages 배열로 변환한다.

    system 이 비어 있으면 system 메시지를 생략해 Gemini(system_instruction=None)와
    동일한 의미를 유지한다.
    """
    messages: list[dict[str, str]] = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    messages.append({"role": "user", "content": req.user})
    return messages


def _to_response(
    completion: object, req: ChapterAIRequest, model: str
) -> ChapterAIResponse:
    """OpenAI chat.completions 응답을 공통 응답 스키마로 변환한다."""
    raw_text = _first_message_text(completion)
    if not raw_text.strip():
        raise ConnectorError("openai_text: 응답 text가 비어 있다.")
    text = _strip_thinking(raw_text)
    return ChapterAIResponse(
        text=text,
        model=model,
        input_tokens=_input_tokens(completion, req),
        output_tokens=_output_tokens(completion, text),
        finish_reason=_finish_reason(completion),
    )


def _first_message_text(completion: object) -> str:
    """첫 번째 choice 의 message.content 를 추출한다."""
    choices = getattr(completion, "choices", None)
    if not isinstance(choices, Sequence) or not choices:
        raise ConnectorError("openai_text: 응답 choices가 비어 있다.")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        raise ConnectorError("openai_text: 응답 message.content가 문자열이 아니다.")
    return content


def _input_tokens(completion: object, req: ChapterAIRequest) -> int:
    usage = getattr(completion, "usage", None)
    value = getattr(usage, "prompt_tokens", None)
    return value if isinstance(value, int) else max(len(req.user) // 4, 0)


def _output_tokens(completion: object, text: str) -> int:
    usage = getattr(completion, "usage", None)
    value = getattr(usage, "completion_tokens", None)
    return value if isinstance(value, int) else max(len(text) // 4, 0)


def _finish_reason(completion: object) -> str:
    choices = getattr(completion, "choices", None)
    if isinstance(choices, Sequence) and choices:
        reason = getattr(choices[0], "finish_reason", None)
        if isinstance(reason, str):
            return reason
    return "stop"


def _map_bad_request(exc: _OpenAIBadRequestError) -> ConnectorError:
    """400 BadRequest 를 컨텍스트 초과 여부에 따라 분기한다."""
    lowered = str(exc).lower()
    if "context" in lowered or "token" in lowered or "too long" in lowered:
        return ContextLengthExceeded(str(exc))
    return ConnectorError(str(exc))
