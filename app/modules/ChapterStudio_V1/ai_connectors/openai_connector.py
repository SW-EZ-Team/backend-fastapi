"""OpenAI GPT 텍스트 폴백 커넥터(ChapterStudio).

ChapterStudio gemini_genai_connector.py 와 동일한 공개 인터페이스
(generate / generate_batch / supports)와 ChapterAIRequest/Response 스키마를 제공한다.
Gemini 텍스트 장애 시 FailoverAIConnector 가 이 커넥터로 회로를 넘긴다.
ClaudeSonnetConnector 처럼 AsyncOpenAI 를 직접 await 한다.
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

# 모델별 completion 토큰 상한 클램프는 루트 공통 헬퍼를 재사용한다
# (app 모듈에서 ai_connectors._gemini_common 등을 import 하는 기존 패턴과 동일).
from ai_connectors._openai_common import clamp_openai_max_tokens
from app.modules.ChapterStudio_V1.ai_connectors.errors import (
    AuthError,
    ConnectorError,
    ContextLengthExceeded,
    RateLimitError,
)
from app.modules.ChapterStudio_V1.ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import (
    ChapterAIRequest,
    ChapterAIResponse,
)
from app.modules.ChapterStudio_V1.common.config import (
    openai_api_key,
    openai_text_model,
)

try:
    from common.llm_output import strip_thinking as _strip_thinking
except ImportError:

    def _strip_thinking(text: str) -> str:
        """공통 정규화 모듈이 없으면 원문을 그대로 반환한다."""
        return text


class OpenAIConnector:
    """OpenAI GPT 텍스트 생성 커넥터(Gemini 폴백)."""

    name = "openai_text"

    def __init__(self) -> None:
        api_key = openai_api_key()
        if api_key is None:
            raise AuthError("OPENAI_API_KEY 가 설정되지 않았다.")
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = openai_text_model()

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """단일 요청을 chat.completions 에 보내고 정규화된 응답을 반환한다."""
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                messages=_build_messages(req),
                temperature=req.temperature,
                # Gemini 용 큰 max_tokens 가 OpenAI 모델 한도를 넘지 않도록 클램프한다.
                max_tokens=clamp_openai_max_tokens(req.max_tokens, self._model),
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
        """Protocol 호환용. 단일 호출 gather다."""
        return list(await asyncio.gather(*[self.generate(req) for req in reqs]))

    async def aclose(self) -> None:
        await self._client.close()

    def supports(self, feature: str) -> bool:
        return feature in {"long_context", "json_mode", "fallback", "openai"}


def _build_messages(req: ChapterAIRequest) -> list[dict[str, str]]:
    """ChapterAIRequest 를 chat.completions messages 배열로 변환한다."""
    messages: list[dict[str, str]] = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    messages.append({"role": "user", "content": req.user})
    return messages


def _to_response(
    completion: object, req: ChapterAIRequest, model: str
) -> ChapterAIResponse:
    raw_text = _first_message_text(completion)
    if not raw_text.strip():
        raise ConnectorError("openai_text: 응답 text가 비어 있다.")
    finish_reason = _finish_reason(completion)
    # 출력 절단(length)이면 깨진 JSON을 다운스트림에 흘리지 않고 명확히 실패시킨다.
    # gemini_flash 커넥터의 MAX_TOKENS 처리와 동일한 방어 — 재생성 경로를 작동시킨다.
    if finish_reason == "length":
        raise ConnectorError(
            f"openai_text: 응답이 max_tokens({req.max_tokens})에서 절단됐다"
            f"(finish_reason={finish_reason}). JSON 불완결로 판단해 재생성을 요청한다."
        )
    text = _strip_thinking(raw_text)
    return ChapterAIResponse(
        text=text,
        model=model,
        input_tokens=_input_tokens(completion, req),
        output_tokens=_output_tokens(completion, text),
        finish_reason=finish_reason,
    )


def _first_message_text(completion: object) -> str:
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
    lowered = str(exc).lower()
    if "context" in lowered or "token" in lowered or "too long" in lowered:
        return ContextLengthExceeded(str(exc))
    return ConnectorError(str(exc))
