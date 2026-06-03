"""Google GenAI SDK 기반 Gemini 텍스트 커넥터."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol

from google import genai
from google.genai import errors as genai_errors

from app.modules.ExamForge_V1.common._ai_schemas import (
    ChapterAIRequest,
    ChapterAIResponse,
    LLMBudgetCounter,
    current_budget,
)
from app.modules.ExamForge_V1.common.config import (
    gemini_text_model,
    google_api_key,
)

# ExamForge용 Gemini genai 동시호출 세마포어 — 지연 생성.
# ChapterStudio _get_genai_semaphore()와 프로세스를 공유하지 않으므로
# ExamForge 경로 독립적으로 제어한다(기본 4, env GEMINI_TEXT_MAX_CONCURRENCY 오버라이드).
_examforge_genai_semaphore: asyncio.Semaphore | None = None


def _get_examforge_genai_semaphore() -> asyncio.Semaphore:
    """ExamForge 전용 Gemini genai 세마포어를 지연 생성해 반환한다."""
    global _examforge_genai_semaphore
    if _examforge_genai_semaphore is None:
        import os
        max_c = max(1, int(os.environ.get("GEMINI_TEXT_MAX_CONCURRENCY", "4")))
        _examforge_genai_semaphore = asyncio.Semaphore(max_c)
    return _examforge_genai_semaphore
from app.modules.ExamForge_V1.common.errors import (
    AuthError,
    ConnectorError,
    ContextLengthExceeded,
    RateLimitError,
)
from app.modules.ExamForge_V1.common.errors import TimeoutError as ConnectorTimeoutError

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
        ...


class _GenAIClient(Protocol):
    models: _GenerateContentModels


class GeminiGenAIConnector:
    """ExamForge용 Gemini Flash google-genai 커넥터."""

    def __init__(self, model_id: str | None = None, connector_name: str = "gemini_flash") -> None:
        api_key = google_api_key()
        if api_key is None:
            raise AuthError(f"{connector_name}: GOOGLE_API_KEY 또는 GEMINI_API_KEY 필요")
        self._client: _GenAIClient = genai.Client(api_key=api_key)
        self._model = model_id or gemini_text_model()
        self.name = connector_name

    async def generate(
        self,
        req: ChapterAIRequest,
        budget: LLMBudgetCounter | None = None,
    ) -> ChapterAIResponse:
        """예산 카운터와 bounded retry를 지키며 Gemini를 호출한다.

        프로세스 전역 세마포어로 동시 genai API 호출을 GEMINI_TEXT_MAX_CONCURRENCY
        이하로 제한해 rate limit 폭주를 방지한다.
        """
        budget = budget or current_budget.get()
        if budget is not None:
            budget.check()

        semaphore = _get_examforge_genai_semaphore()
        for attempt in range(_MAX_ATTEMPTS):
            try:
                async with semaphore:
                    response = await asyncio.to_thread(self._generate_sync, req)
                result = _to_response(response, req, self._model)
                if budget is not None:
                    budget.increment()
                return result
            except (RateLimitError, ConnectorTimeoutError):
                if attempt >= _MAX_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(_RETRY_DELAYS[attempt])
        raise ConnectorError("gemini_flash: 재시도 루프가 비정상 종료됐다.")

    def supports(self, feature: str) -> bool:
        """지원 기능 확인."""
        return feature in {"long_context", "json_mode", "google_genai"}

    def _generate_sync(self, req: ChapterAIRequest) -> object:
        config = genai.types.GenerateContentConfig(
            system_instruction=req.system or None,
            temperature=req.temperature,
            max_output_tokens=req.max_tokens,
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
