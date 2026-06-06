"""Google GenAI Gemini Flash 텍스트 커넥터."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol

from google import genai
from google.genai import errors as genai_errors

from ai_connectors.errors import (
    AuthError,
    ConnectorError,
    ContextLengthExceeded,
    RateLimitError,
)
from ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from ai_connectors.text_schemas import ChapterAIRequest, ChapterAIResponse
from common.text_config import gemini_text_model, gemini_thinking_level, google_api_key

try:
    from common.llm_output import strip_thinking as _strip_thinking
except ImportError:

    def _strip_thinking(text: str) -> str:
        """공통 정규화 모듈이 없으면 원문을 그대로 반환한다."""
        return text


_MAX_ATTEMPTS = 3
_RETRY_DELAYS: tuple[float, float] = (1.0, 2.0)


class _GenerateContentModels(Protocol):
    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        """google-genai 동기 generate_content 호출 형태."""
        ...


class _GenAIClient(Protocol):
    models: _GenerateContentModels

    def close(self) -> None:
        """동기 클라이언트 리소스를 닫는다."""
        ...


class GeminiGenAIConnector:
    """Google AI Studio Gemini 텍스트 생성 커넥터."""

    name = "gemini_flash"

    def __init__(self) -> None:
        api_key = google_api_key()
        if api_key is None:
            raise AuthError("GOOGLE_API_KEY 또는 GEMINI_API_KEY가 설정되지 않았다.")
        self._client: _GenAIClient = genai.Client(api_key=api_key)
        self._model = gemini_text_model()
        # gemini-3.5-flash는 thinking 모델이라 사고량이 크면 reasoning 텍스트가 답변
        # 본문으로 새어 나온다. thinking_level을 LOW(기본)로 낮춰 추론 노출을 차단한다.
        self._thinking_level = gemini_thinking_level()

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """동기 google-genai SDK 호출을 스레드로 감싸 텍스트를 생성한다."""
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await asyncio.to_thread(self._generate_sync, req)
                return _to_response(response, req, self._model)
            except (RateLimitError, ConnectorTimeoutError):
                if attempt >= _MAX_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(_RETRY_DELAYS[attempt])
        raise ConnectorError("gemini_flash: 재시도 루프가 비정상 종료됐다.")

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        """호환성용 배치 처리. 모델 자체 배치가 아니라 단일 호출 gather다."""
        return list(await asyncio.gather(*[self.generate(req) for req in reqs]))

    async def aclose(self) -> None:
        """google-genai 동기 클라이언트를 스레드에서 닫는다."""
        await asyncio.to_thread(self._client.close)

    def supports(self, feature: str) -> bool:
        return feature in {"long_context", "json_mode", "fallback", "google_genai"}

    def _generate_sync(self, req: ChapterAIRequest) -> object:
        """google-genai 동기 API를 정확한 파라미터로 호출한다."""
        config = genai.types.GenerateContentConfig(
            system_instruction=req.system or None,
            temperature=req.temperature,
            max_output_tokens=req.max_tokens,
            # Gemini 3 계열은 thinking_budget 미지원 → thinking_level로 사고량을 제어한다.
            # reasoning 스크래치패드가 최종 답변에 노출되는 것을 모델 단에서 막는다.
            thinking_config=genai.types.ThinkingConfig(
                thinking_level=self._thinking_level
            ),
        )
        try:
            return self._client.models.generate_content(
                model=self._model,
                contents=req.user,
                config=config,
            )
        except genai_errors.APIError as exc:
            raise _map_api_error(exc) from exc
        except (TimeoutError, OSError) as exc:
            raise ConnectorTimeoutError(str(exc)) from exc


def _to_response(
    response: object, req: ChapterAIRequest, model: str
) -> ChapterAIResponse:
    """Gemini 응답 객체를 공통 응답 스키마로 변환한다."""
    raw_text = getattr(response, "text", None)
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ConnectorError("gemini_flash: 응답 text가 비어 있다.")
    text = _strip_thinking(raw_text)
    return ChapterAIResponse(
        text=text,
        model=model,
        input_tokens=_input_tokens(response, req),
        output_tokens=_output_tokens(response, text),
        finish_reason=_finish_reason(response),
    )


def _input_tokens(response: object, req: ChapterAIRequest) -> int:
    usage = getattr(response, "usage_metadata", None)
    value = _usage_int(usage, ("prompt_token_count", "input_token_count"))
    return value if value is not None else max(len(req.user) // 4, 0)


def _output_tokens(response: object, text: str) -> int:
    usage = getattr(response, "usage_metadata", None)
    value = _usage_int(usage, ("candidates_token_count", "output_token_count"))
    return value if value is not None else max(len(text) // 4, 0)


def _usage_int(usage: object, names: tuple[str, ...]) -> int | None:
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int):
            return value
    return None


def _finish_reason(response: object) -> str:
    candidates = getattr(response, "candidates", None)
    if isinstance(candidates, Sequence) and candidates:
        reason = getattr(candidates[0], "finish_reason", None)
        if reason is not None:
            return str(reason)
    return "stop"


def _map_api_error(exc: genai_errors.APIError) -> ConnectorError:
    """google-genai APIError를 공통 커넥터 예외로 변환한다."""
    code = getattr(exc, "code", None)
    message = str(exc)
    if code in {401, 403}:
        return AuthError(message)
    if code == 429:
        return RateLimitError(message)
    if code in {408, 500, 502, 503, 504}:
        return ConnectorTimeoutError(message)
    if code == 400 and _looks_like_context_error(message):
        return ContextLengthExceeded(message)
    return ConnectorError(message)


def _looks_like_context_error(message: str) -> bool:
    lowered = message.lower()
    return "context" in lowered or "token" in lowered or "too long" in lowered
