"""Google GenAI Gemini Flash 텍스트 커넥터."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from google import genai
from google.genai import errors as genai_errors

from ai_connectors import _gemini_throttle as _throttle
from ai_connectors.errors import (
    AuthError,
    ConnectorError,
    ContextLengthExceeded,
    RateLimitError,
    ServiceUnavailableError,
)
from ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from ai_connectors.text_schemas import ChapterAIRequest, ChapterAIResponse
from common.text_config import (
    gemini_text_max_concurrency,
    gemini_text_model,
    gemini_thinking_level,
    google_api_key,
)

try:
    from common.llm_output import strip_thinking as _strip_thinking
except ImportError:

    def _strip_thinking(text: str) -> str:
        """공통 정규화 모듈이 없으면 원문을 그대로 반환한다."""
        return text


_LOG = logging.getLogger(__name__)

# 재시도·모델 폴백 대상 예외 — 429 / 503·UNAVAILABLE / 타임아웃 계열
_RETRYABLE_ERRORS = (RateLimitError, ServiceUnavailableError, ConnectorTimeoutError)

# ── 실제 동시 SDK 호출 상한 강제용 bounded ThreadPoolExecutor ──────────────
# [백로그 #1] asyncio.to_thread 는 이벤트루프 기본 executor(스레드 수 사실상 무제한)에
# blocking 호출을 던진다. asyncio.wait_for 가 타임아웃하면 *대기 코루틴*만 풀리고
# blocking google-genai 호출은 기본 executor 스레드에서 계속 돈다 → 타임아웃 다발 시
# 실 SDK 호출이 무제한으로 누적될 수 있다(스레드 누수). 전역 커넥터는 동시성
# 세마포어가 없어 스로틀 간격에만 의존하므로, 누수 호출의 하드 상한이 없다.
#
# 해결: blocking 호출을 크기 제한된 프로세스 전역 executor 로만 실행한다. 워커 수가
# GEMINI_TEXT_MAX_CONCURRENCY(기본 1)로 고정되므로, 타임아웃으로 누수된(아직 도는)
# 호출도 워커를 계속 점유한다. 새 제출은 새 스레드 없이 큐 대기(큐 무제한 → 이벤트
# 루프 비차단, 데드락 없음). 따라서 *실제 동시 SDK 호출 수*가 워커 수 이하로 강제된다.
_sdk_executor: ThreadPoolExecutor | None = None


def _get_sdk_executor() -> ThreadPoolExecutor:
    """실 SDK 호출 전용 bounded ThreadPoolExecutor 를 지연 생성해 반환한다.

    워커 수 = GEMINI_TEXT_MAX_CONCURRENCY(기본 1). 이 풀이 *실제 동시 SDK 호출*의
    하드 상한이다 — wait_for 타임아웃으로 코루틴이 풀려도 blocking 호출은 워커를
    계속 점유하므로 누수 호출까지 포함해 동시 실행이 워커 수를 넘지 않는다.
    """
    global _sdk_executor
    if _sdk_executor is None:
        _sdk_executor = ThreadPoolExecutor(
            max_workers=gemini_text_max_concurrency(),
            thread_name_prefix="gemini-text-sdk",
        )
    return _sdk_executor


def reset_sdk_executor() -> None:
    """전역 SDK executor 캐시를 초기화한다 — 테스트에서 동시성 env 변경 후 재생성용.

    기존 executor 는 wait=False 로 셧다운한다(누수 스레드가 있어도 블록하지 않음).
    """
    global _sdk_executor
    if _sdk_executor is not None:
        _sdk_executor.shutdown(wait=False)
    _sdk_executor = None


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
        """동기 google-genai SDK 호출을 스레드로 감싸 텍스트를 생성한다.

        모델당 환경변수 기반 지수 백오프 재시도를 수행하고, 429/503/타임아웃으로
        재시도가 소진되면 GEMINI_TEXT_MODEL_FALLBACKS 순서대로 다음 모델로
        넘어간다. 모든 모델이 실패해야 마지막 오류를 올린다(프로바이더 폴백 트리거).
        """
        models = _throttle.model_chain(self._model)
        last_error: ConnectorError | None = None
        for index, model in enumerate(models):
            if index > 0:
                _LOG.warning(
                    "gemini_flash: 모델 폴백 전환 %s → %s (사유: %s)",
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
        """단일 모델에 대해 스로틀 + 지수 백오프 재시도를 수행한다."""
        attempts = _throttle.retry_attempts()
        last_error: ConnectorError | None = None
        for attempt in range(attempts):
            # 모든 시도 직전에 호출 시작 간격 스로틀을 적용한다
            await _throttle.wait_for_slot()
            try:
                response = await self._call_sdk(req, model)
                return _to_response(response, req, model)
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt < attempts - 1:
                    delay = _throttle.backoff_delay_sec(attempt)
                    _LOG.warning(
                        "gemini_flash[%s]: 시도 %d/%d 실패(%s). %.1f초 후 재시도",
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
        executor(workers=GEMINI_TEXT_MAX_CONCURRENCY)에 blocking 호출을 제출한다.
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
            # shield 로 감싸 wait_for 타임아웃이 executor future 를 취소하려 들지
            # 않게 한다(blocking 스레드는 어차피 취소 불가 — 워커 회계 의미를 명확히).
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise ConnectorTimeoutError(
                f"gemini_flash[{model}]: {timeout:.0f}초 내 응답 없음 (GEMINI_TEXT_TIMEOUT_MS)"
            ) from exc

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

    def _generate_sync(self, req: ChapterAIRequest, model: str | None = None) -> object:
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
        # 429는 두 부류로 나뉜다:
        #  - billing_exhausted: 선불 크레딧 소진·결제 중단 등 영구성. 재시도·모델 폴백이
        #    무의미하므로 비재시도 ConnectorError로 올려 상위 프로바이더 폴백
        #    (OpenAI→Claude)이 즉시 전환하게 한다.
        #  - quota/rate_limit: 분당 요청 초과 등 일시성. RateLimitError(재시도 대상).
        # 구조화 필드(status/details.reason/code)를 우선 보고, 없으면 메시지 문자열
        # 마커로 폴백한다(이중 안전).
        if _is_billing_exhausted_429(exc, message):
            return ConnectorError(f"Gemini 결제 크레딧 소진 — 즉시 폴백: {message}")
        return RateLimitError(message)
    # 503/UNAVAILABLE/overloaded 는 과부하 — 재시도·모델 폴백 대상으로 구분한다
    if code == 503 or _looks_like_overloaded(message):
        return ServiceUnavailableError(message)
    if code in {408, 500, 502, 504}:
        return ConnectorTimeoutError(message)
    if code == 400 and _looks_like_context_error(message):
        return ContextLengthExceeded(message)
    return ConnectorError(message)


# 영구성 429(결제 중단·크레딧 소진)를 가리키는 구조화 reason 코드.
# google API의 details[].reason 필드값이며, status=RESOURCE_EXHAUSTED는
# 일시적 quota 초과와도 공유되므로 reason 으로 영구/일시를 구분한다.
_BILLING_EXHAUSTED_REASONS = frozenset(
    {
        "BILLING_DISABLED",
        "ACCOUNT_SUSPENDED",
        "BILLING_REQUIRED",
        "PREPAYMENT_REQUIRED",
        "CONSUMER_SUSPENDED",
    }
)

# 일시성 429(분당 요청·토큰 quota 초과)를 가리키는 구조화 reason 코드.
# 이 reason 들은 명시적으로 재시도 대상으로 분류해, billing 마커 오탐을 막는다.
_TRANSIENT_QUOTA_REASONS = frozenset(
    {
        "RATE_LIMIT_EXCEEDED",
        "RESOURCE_EXHAUSTED",
        "QUOTA_EXCEEDED",
    }
)

# 메시지 문자열 폴백 마커 — 구조화 필드가 없을 때만 쓰는 이중 안전망.
_BILLING_EXHAUSTED_MARKERS = (
    "credits are depleted",
    "prepayment",
    "billing",
    "manage your project",
)


def _iter_error_reasons(exc: object) -> tuple[str, ...]:
    """APIError.details(원본 response_json)에서 details[].reason 값들을 추출한다.

    google 429 payload 형태:
        {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                   "details": [{"reason": "BILLING_DISABLED", ...}, ...]}}
    details 위치가 최상위/error 하위 어디든 견고하게 훑어 reason 문자열만 모은다.
    """
    details = getattr(exc, "details", None)
    if not isinstance(details, dict):
        return ()
    # 최상위 또는 error 하위 어디에 있든 details 배열을 찾는다
    candidates = [details]
    error_obj = details.get("error")
    if isinstance(error_obj, dict):
        candidates.append(error_obj)
    reasons: list[str] = []
    for obj in candidates:
        detail_list = obj.get("details")
        if isinstance(detail_list, list):
            for item in detail_list:
                if isinstance(item, dict):
                    reason = item.get("reason")
                    if isinstance(reason, str) and reason:
                        reasons.append(reason.upper())
    return tuple(reasons)


def _is_billing_exhausted_429(exc: object, message: str) -> bool:
    """일시적 rate limit과 구분되는 영구성 429(크레딧 소진·결제 중단)인지 판별한다.

    분류 우선순위:
    1) 구조화 reason — billing_exhausted reason 이 하나라도 있으면 영구성으로 확정.
    2) 구조화 reason — transient quota reason 만 있으면 일시성으로 확정(billing 마커 무시).
    3) 구조화 reason 부재 — 메시지 문자열 마커로 폴백 판별(이중 안전).
    """
    reasons = _iter_error_reasons(exc)
    if reasons:
        if any(reason in _BILLING_EXHAUSTED_REASONS for reason in reasons):
            return True
        if all(reason in _TRANSIENT_QUOTA_REASONS for reason in reasons):
            return False
        # 알 수 없는 reason 조합이면 메시지 마커로 마저 판별한다(아래로 폴스루).
    return _message_has_billing_marker(message)


def _message_has_billing_marker(message: str) -> bool:
    """구조화 필드가 없을 때 쓰는 메시지 문자열 폴백 판별."""
    low = message.lower()
    return any(marker in low for marker in _BILLING_EXHAUSTED_MARKERS)


def _looks_like_overloaded(message: str) -> bool:
    """503 류 과부하 메시지 패턴(UNAVAILABLE/overloaded)을 식별한다."""
    lowered = message.lower()
    return "unavailable" in lowered or "overloaded" in lowered


def _looks_like_context_error(message: str) -> bool:
    lowered = message.lower()
    return "context" in lowered or "token" in lowered or "too long" in lowered
