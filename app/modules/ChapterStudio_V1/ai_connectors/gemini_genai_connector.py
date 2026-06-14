from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from google import genai
from google.genai import errors as genai_errors

# Gemini 안정화 공통 정책 — 루트 ai_connectors 와 스로틀/백오프/모델 폴백을 공유한다
from ai_connectors import _gemini_throttle as _throttle
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
    gemini_text_max_concurrency,
    gemini_text_model,
    google_api_key,
)

try:
    from common.llm_output import strip_thinking as _strip_thinking
except ImportError:

    def _strip_thinking(text: str) -> str:
        """공통 정규화 모듈이 없으면 원문을 그대로 반환한다."""
        return text


_LOG = logging.getLogger(__name__)

# 재시도·모델 폴백 대상 예외 — 429 / 503·타임아웃 계열(이 모듈은 503을 Timeout으로 매핑)
_RETRYABLE_ERRORS = (RateLimitError, ConnectorTimeoutError)

# 프로세스 전역 Gemini genai 동시호출 세마포어 — 지연 생성(이벤트 루프 안전).
# GeminiCliConnector의 asyncio.Lock(CLI 모드 직렬)과는 별개의 제어다.
_genai_semaphore: asyncio.Semaphore | None = None

# ── 실제 동시 SDK 호출 상한 강제용 bounded ThreadPoolExecutor ──────────────
# [백로그 #1] _call_sdk 가 asyncio.wait_for(asyncio.to_thread(...)) 형태라, wait_for
# 타임아웃 시 awaiting 코루틴만 풀리고 async with semaphore 가 즉시 풀려 세마포어
# 슬롯이 반환된다 — 그러나 blocking SDK 호출은 기본 executor 스레드에서 계속 돈다.
# → 세마포어 상한 밖에서 실 SDK 호출이 누적될 수 있다(스레드 누수). 해결: blocking
# 호출을 크기 제한된 전용 executor(워커 수 = gemini_text_max_concurrency)로만 실행해
# *실제 동시 SDK 호출*을 워커 수 이하로 강제한다(타임아웃으로 누수된 호출도 워커 점유).
_sdk_executor: ThreadPoolExecutor | None = None


def _get_genai_semaphore() -> asyncio.Semaphore:
    """Gemini genai API 동시호출 세마포어를 지연 생성해 반환한다."""
    global _genai_semaphore
    if _genai_semaphore is None:
        _genai_semaphore = asyncio.Semaphore(gemini_text_max_concurrency())
    return _genai_semaphore


def _get_sdk_executor() -> ThreadPoolExecutor:
    """실 SDK 호출 전용 bounded ThreadPoolExecutor 를 지연 생성해 반환한다.

    워커 수 = gemini_text_max_concurrency(). 이 풀이 *실제 동시 SDK 호출*의 하드
    상한이다 — wait_for 타임아웃으로 코루틴이 풀려도 blocking 호출은 워커를 계속
    점유하므로 누수 호출까지 포함해 동시 실행이 워커 수를 넘지 않는다.
    """
    global _sdk_executor
    if _sdk_executor is None:
        _sdk_executor = ThreadPoolExecutor(
            max_workers=gemini_text_max_concurrency(),
            thread_name_prefix="chapter-gemini-sdk",
        )
    return _sdk_executor


def reset_sdk_executor() -> None:
    """전용 SDK executor 캐시를 초기화한다 — 테스트에서 동시성 env 변경 후 재생성용."""
    global _sdk_executor
    if _sdk_executor is not None:
        _sdk_executor.shutdown(wait=False)
    _sdk_executor = None


class _GenerateContentModels(Protocol):
    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        ...


class _GenAIClient(Protocol):
    models: _GenerateContentModels

    def close(self) -> None:
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

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """동기 SDK 호출을 asyncio.to_thread로 감싸 블로킹을 막는다.

        프로세스 전역 세마포어로 동시 genai API 호출을 gemini_text_max_concurrency()
        이하로 제한하고, 환경변수 기반 스로틀·지수 백오프·모델 폴백으로
        rate limit / 503 폭주를 방지한다.
        """
        models = _throttle.model_chain(self._model)
        last_error: ConnectorError | None = None
        for index, model in enumerate(models):
            if index > 0:
                _LOG.warning(
                    "%s: 모델 폴백 전환 %s → %s (사유: %s)",
                    self.name,
                    models[index - 1],
                    model,
                    last_error,
                )
            try:
                return await self._generate_with_retry(req, model)
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
        if last_error is None:
            raise ConnectorError("gemini_flash: 재시도 루프가 비정상 종료됐다.")
        raise last_error

    async def _generate_with_retry(
        self, req: ChapterAIRequest, model: str
    ) -> ChapterAIResponse:
        """단일 모델에 대해 세마포어 + 스로틀 + 지수 백오프 재시도를 수행한다."""
        semaphore = _get_genai_semaphore()
        attempts = _throttle.retry_attempts()
        last_error: ConnectorError | None = None
        for attempt in range(attempts):
            try:
                async with semaphore:
                    # 모든 시도 직전에 호출 시작 간격 스로틀을 적용한다
                    await _throttle.wait_for_slot()
                    response = await self._call_sdk(req, model)
                return _to_response(response, req, model)
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt < attempts - 1:
                    delay = _throttle.backoff_delay_sec(attempt)
                    _LOG.warning(
                        "%s[%s]: 시도 %d/%d 실패(%s). %.1f초 후 재시도",
                        self.name,
                        model,
                        attempt + 1,
                        attempts,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
        if last_error is None:
            raise ConnectorError("gemini_flash: 재시도 루프가 비정상 종료됐다.")
        raise last_error

    async def _call_sdk(self, req: ChapterAIRequest, model: str) -> object:
        """SDK 호출을 bounded executor 로 감싸고 GEMINI_TEXT_TIMEOUT_MS 타임아웃을 적용한다.

        [백로그 #1] asyncio.to_thread(기본 무제한 executor) 대신 크기 제한된 전용
        executor(워커 수 = gemini_text_max_concurrency)에 blocking 호출을 제출한다.
        wait_for 타임아웃 시 awaiting future 는 풀리지만 blocking 호출은 워커를 계속
        점유하므로, 누수된 호출까지 포함해 *실제 동시 SDK 호출*이 워커 수를 넘지 못한다.
        """
        loop = asyncio.get_running_loop()
        executor = _get_sdk_executor()
        future = loop.run_in_executor(executor, self._generate_sync, req, model)
        timeout = _throttle.request_timeout_sec()
        if timeout is None:
            return await future
        try:
            # shield 로 감싸 wait_for 타임아웃이 executor future 를 취소하려 들지 않게 한다.
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise ConnectorTimeoutError(
                f"{self.name}[{model}]: {timeout:.0f}초 내 응답 없음 (GEMINI_TEXT_TIMEOUT_MS)"
            ) from exc

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        """Protocol 호환용. Qwen 전용 병렬 생성 경로로는 광고하지 않는다."""
        return list(await asyncio.gather(*[self.generate(req) for req in reqs]))

    async def aclose(self) -> None:
        await asyncio.to_thread(self._client.close)

    def supports(self, feature: str) -> bool:
        return feature in {"long_context", "json_mode", "fallback", "google_genai"}

    def _generate_sync(self, req: ChapterAIRequest, model: str | None = None) -> object:
        config = genai.types.GenerateContentConfig(
            system_instruction=req.system or None,
            temperature=req.temperature,
            max_output_tokens=req.max_tokens,
        )
        try:
            return self._client.models.generate_content(
                model=model or self._model,
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
    finish_reason = _finish_reason(response)
    # 출력 절단(MAX_TOKENS)이면 깨진 JSON을 다운스트림에 흘리지 않고 명확히 실패시킨다.
    # gemini-3.5-flash는 thinking 토큰(실측 0~20000+ 변동)이 max_output_tokens를 잠식해
    # 긴 레슨 JSON을 문장 중간에서 절단한다(Unterminated string/Expecting ',' delimiter).
    # ConnectorError를 올리면 _parse_with_backfill/_component의 재생성 경로가 작동한다(silent-fail 금지).
    if "MAX_TOKENS" in finish_reason:
        raise ConnectorError(
            f"gemini_flash: 응답이 max_output_tokens({req.max_tokens})에서 절단됐다"
            f"(finish_reason={finish_reason}). JSON 불완결로 판단해 재생성을 요청한다."
        )
    text = _strip_thinking(raw_text)
    return ChapterAIResponse(
        text=text,
        model=model,
        input_tokens=_input_tokens(response, req),
        output_tokens=_output_tokens(response, text),
        finish_reason=finish_reason,
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
