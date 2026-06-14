"""Google GenAI SDK 기반 Gemini 텍스트 커넥터."""
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
from app.modules.ExamForge_V1.common._ai_schemas import (
    ChapterAIRequest,
    ChapterAIResponse,
    LLMBudgetCounter,
    current_budget,
)
from app.modules.ExamForge_V1.common.config import (
    examforge_gemini_concurrency,
    gemini_text_model,
    google_api_key,
)

# ── ExamForge 전용 Gemini 레인 ───────────────────────────────────────────
# 모의고사 생성은 수십 개의 독립 Gemini 호출을 묶어 실행한다. 전역(채팅·강의)
# 레인의 보수적 스로틀(GEMINI_REQUEST_INTERVAL_MS=2000, 직렬화)을 그대로 타면
# 750초 파이프라인 타임아웃에 걸린다. 그래서 ExamForge 만 전용 레인을 쓴다:
# - 전용 throttle 레인 이름(전역 상태와 격리된 lock + next_allowed_at)
# - 전용 간격 환경변수(EXAMFORGE_GEMINI_INTERVAL_MS, 기본 600ms)
# - 전용 동시성 세마포어(EXAMFORGE_GEMINI_CONCURRENCY, 기본 3)
# 전역 GEMINI_TEXT_MAX_CONCURRENCY / GEMINI_REQUEST_INTERVAL_MS 는 건드리지 않아
# 채팅·강의 경로(latency 민감)는 기존 보수값 그대로 보호된다.
_EXAMFORGE_THROTTLE_LANE = "examforge_gemini"
_EXAMFORGE_INTERVAL_ENV = "EXAMFORGE_GEMINI_INTERVAL_MS"
# env 미설정 시에도 코드 기본값으로 600ms 간격이 적용되도록 한다(429 방어).
# EXAMFORGE_GEMINI_INTERVAL_MS=0 을 명시하면 스로틀 비활성(최대 속도).
_EXAMFORGE_INTERVAL_DEFAULT_MS = 600

# ExamForge용 Gemini genai 동시호출 세마포어 — 지연 생성.
# 전역 ai_connectors 세마포어/ChapterStudio 세마포어와 프로세스를 공유하지 않는다.
_examforge_genai_semaphore: asyncio.Semaphore | None = None

# ── 실제 동시 SDK 호출 상한 강제용 bounded ThreadPoolExecutor ──────────────
# [백로그 #1] 기존 구조 결함: _call_sdk 가 asyncio.wait_for(asyncio.to_thread(...))
# 형태였다. asyncio.to_thread 는 이벤트루프 기본 executor(스레드 수 무제한에
# 가까움)에 작업을 던진다. wait_for 가 타임아웃하면 *대기 코루틴*만 취소되고
# async with semaphore 블록이 풀려 세마포어 슬롯이 즉시 반환된다 — 그러나
# 실제 blocking SDK 호출은 기본 executor 스레드에서 계속 돈다. 그 결과 세마포어
# "동시성 3" 밖에서 실 SDK 호출이 누적될 수 있다(모의고사 2개 동시 생성 시 특히).
#
# 해결: 세마포어와 무관하게 *실제* blocking SDK 호출을 크기 제한된 전용
# ThreadPoolExecutor 로만 실행한다. 워커 스레드 수가 EXAMFORGE_GEMINI_CONCURRENCY
# 로 고정되므로, 타임아웃으로 누수된(아직 도는) 호출도 워커를 계속 점유한다.
# 새 제출은 새 스레드를 만들지 않고 큐에서 대기한다(큐는 무제한 → 이벤트루프를
# 막지 않아 데드락 없음). 따라서 *실제 동시 SDK 호출 수*가 워커 수 이하로 강제된다.
_examforge_sdk_executor: ThreadPoolExecutor | None = None


def _get_examforge_genai_semaphore() -> asyncio.Semaphore:
    """ExamForge 전용 Gemini genai 세마포어를 지연 생성해 반환한다.

    크기는 EXAMFORGE_GEMINI_CONCURRENCY(기본 3)에서 읽는다 — 전역
    GEMINI_TEXT_MAX_CONCURRENCY(=1)와 무관한 전용 동시성이다.
    """
    global _examforge_genai_semaphore
    if _examforge_genai_semaphore is None:
        _examforge_genai_semaphore = asyncio.Semaphore(examforge_gemini_concurrency())
    return _examforge_genai_semaphore


def _get_examforge_sdk_executor() -> ThreadPoolExecutor:
    """실 SDK 호출 전용 bounded ThreadPoolExecutor 를 지연 생성해 반환한다.

    워커 수 = EXAMFORGE_GEMINI_CONCURRENCY(기본 3). 이 풀이 *실제 동시 SDK 호출*의
    하드 상한이다. wait_for 타임아웃으로 코루틴이 풀려도 blocking 호출은 워커를
    계속 점유하므로, 누수된 호출까지 포함해 동시 실행이 워커 수를 넘지 않는다.
    """
    global _examforge_sdk_executor
    if _examforge_sdk_executor is None:
        workers = examforge_gemini_concurrency()
        _examforge_sdk_executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="examforge-gemini-sdk",
        )
    return _examforge_sdk_executor


def reset_examforge_genai_semaphore() -> None:
    """전용 세마포어 캐시를 초기화한다 — 테스트에서 동시성 env 변경 후 재생성용."""
    global _examforge_genai_semaphore
    _examforge_genai_semaphore = None


def reset_examforge_sdk_executor() -> None:
    """전용 SDK executor 캐시를 초기화한다 — 테스트에서 동시성 env 변경 후 재생성용.

    기존 executor 는 wait=False 로 셧다운한다(누수 스레드가 있어도 블록하지 않음).
    """
    global _examforge_sdk_executor
    if _examforge_sdk_executor is not None:
        _examforge_sdk_executor.shutdown(wait=False)
    _examforge_sdk_executor = None
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


_LOG = logging.getLogger(__name__)

# 재시도·모델 폴백 대상 예외 — 429 / 503·타임아웃 계열(이 모듈은 503을 Timeout으로 매핑)
_RETRYABLE_ERRORS = (RateLimitError, ConnectorTimeoutError)


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
                result = await self._generate_with_retry(req, model)
                if budget is not None:
                    budget.increment()
                return result
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
        if last_error is None:
            raise ConnectorError("gemini_flash: 재시도 루프가 비정상 종료됐다.")
        raise last_error

    async def _generate_with_retry(
        self, req: ChapterAIRequest, model: str
    ) -> ChapterAIResponse:
        """단일 모델에 대해 세마포어 + 스로틀 + 지수 백오프 재시도를 수행한다."""
        semaphore = _get_examforge_genai_semaphore()
        attempts = _throttle.retry_attempts()
        last_error: ConnectorError | None = None
        for attempt in range(attempts):
            try:
                async with semaphore:
                    # 모든 시도 직전에 호출 시작 간격 스로틀을 적용한다.
                    # ExamForge 전용 레인 + 전용 간격 환경변수를 써서 전역(채팅·강의)
                    # 스로틀과 격리된다 — 전역 2000ms 직렬화에 굶지 않는다.
                    await _throttle.wait_for_slot(
                        lane=_EXAMFORGE_THROTTLE_LANE,
                        interval_env=_EXAMFORGE_INTERVAL_ENV,
                        default_ms=_EXAMFORGE_INTERVAL_DEFAULT_MS,
                    )
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
        executor(workers=EXAMFORGE_GEMINI_CONCURRENCY)에 blocking 호출을 제출한다.
        wait_for 타임아웃 시 awaiting future 는 취소되지만 blocking 호출은 워커를
        계속 점유하므로, 누수된 호출까지 포함해 *실제 동시 SDK 호출*이 워커 수를
        넘지 못한다(세마포어만으로는 못 막는 부분을 executor 가 하드 상한으로 강제).
        """
        loop = asyncio.get_running_loop()
        executor = _get_examforge_sdk_executor()
        # run_in_executor 는 전용 executor 에 제출하고 awaitable future 를 돌려준다.
        future = loop.run_in_executor(executor, self._generate_sync, req, model)
        timeout = _throttle.request_timeout_sec()
        if timeout is None:
            return await future
        try:
            # shield 로 감싸 wait_for 타임아웃이 executor future 자체를
            # 취소하려 시도하지 않게 한다(blocking 스레드는 어차피 취소 불가이므로
            # 표면적 취소가 워커 회계를 오염시키지 않도록 의미를 명확히 한다).
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise ConnectorTimeoutError(
                f"{self.name}[{model}]: {timeout:.0f}초 내 응답 없음 (GEMINI_TEXT_TIMEOUT_MS)"
            ) from exc

    def supports(self, feature: str) -> bool:
        """지원 기능 확인."""
        return feature in {"long_context", "json_mode", "google_genai"}

    def _generate_sync(self, req: ChapterAIRequest, model: str | None = None) -> object:
        config_kwargs = dict(
            system_instruction=req.system or None,
            temperature=req.temperature,
            max_output_tokens=req.max_tokens,
        )
        # 자유서술 출력(AI총평 등)은 gemini-3.x flash 의 인라인 reasoning 이 본문에 섞여
        # 누출된다(JSON 파싱으로 걸러지는 생성 경로와 달리 free-text 라 정제가 불완전).
        # 호출부가 extra={"thinking_budget": 0} 을 주면 thinking 을 꺼 누출을 원천 차단한다.
        # (생성 경로는 extra 미지정 → 기존 thinking 동작 유지하여 출제 품질 보존.)
        thinking_budget = req.extra.get("thinking_budget")
        if thinking_budget is not None:
            try:
                config_kwargs["thinking_config"] = genai.types.ThinkingConfig(
                    thinking_budget=int(thinking_budget)
                )
            except (TypeError, ValueError, AttributeError):
                pass
        config = genai.types.GenerateContentConfig(**config_kwargs)
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


# 영구성 429(선불 크레딧 소진·결제 중단) — 일시적 rate limit과 구분한다.
# 이런 429는 재시도·모델 폴백을 해도 동일 결제계정이라 전부 실패하므로,
# 즉시 프로바이더 폴백(OpenAI→Claude)으로 넘겨 ~45초 낭비를 막는다.
#
# status=RESOURCE_EXHAUSTED는 결제 소진·분당 quota 초과가 공유하므로,
# google API의 details[].reason 구조화 필드를 우선 보고 영구/일시를 가른다.
# 루트 ai_connectors.text.gemini_connector 와 동일한 reason 집합·우선순위를 쓴다.
_BILLING_EXHAUSTED_REASONS = frozenset(
    {
        "BILLING_DISABLED",
        "ACCOUNT_SUSPENDED",
        "BILLING_REQUIRED",
        "PREPAYMENT_REQUIRED",
        "CONSUMER_SUSPENDED",
    }
)

# 일시성 429(분당 요청·토큰 quota 초과) reason — 명시적 재시도 대상.
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
    2) 구조화 reason — transient quota reason 만 있으면 일시성으로 확정.
    3) 구조화 reason 부재 — 메시지 문자열 마커로 폴백 판별(이중 안전).
    """
    reasons = _iter_error_reasons(exc)
    if reasons:
        if any(reason in _BILLING_EXHAUSTED_REASONS for reason in reasons):
            return True
        if all(reason in _TRANSIENT_QUOTA_REASONS for reason in reasons):
            return False
    return _message_has_billing_marker(message)


def _message_has_billing_marker(message: str) -> bool:
    """구조화 필드가 없을 때 쓰는 메시지 문자열 폴백 판별."""
    low = message.lower()
    return any(marker in low for marker in _BILLING_EXHAUSTED_MARKERS)


def _record_provider_exhausted(provider: str, message: str) -> None:
    """프로바이더 헬스 캐시에 소진을 passive 기록한다(라이브 프로빙 아님).

    헬스 모듈 임포트/기록 실패는 절대 생성 경로를 깨뜨리지 않도록 폭넓게 흡수한다 —
    이 기록은 어디까지나 다음 생성 사전점검을 위한 best-effort 부가 신호다.
    """
    try:
        from app.modules.ExamForge_V1.common import _provider_health as health

        until = health.parse_regain_until(message)
        health.mark_exhausted(provider, reason=message[:200], until_monotonic=until)
    except Exception:  # noqa: BLE001 — 헬스 기록 실패가 생성 경로를 깨면 안 된다
        _LOG.debug("[ProviderHealth] '%s' 소진 기록 실패(무시)", provider, exc_info=True)


def _map_api_error(exc: genai_errors.APIError) -> ConnectorError:
    code = getattr(exc, "code", None)
    message = str(exc)
    if code in {401, 403}:
        return AuthError(message)
    if code == 429:
        # 결제성 429는 비재시도 ConnectorError로 올려 모델 폴백 루프를 건너뛰고
        # 상위 프로바이더 폴백 래퍼가 즉시 OpenAI/Claude로 전환하게 한다.
        # 구조화 reason 우선, 메시지 마커 폴백(이중 안전).
        if _is_billing_exhausted_429(exc, message):
            # passive 기록: 이 결제성 소진은 같은 계정이라 재시도해도 전부 실패하므로
            # gemini_flash 를 소진으로 표시한다(다음 생성 사전점검이 즉시 빠지게).
            _record_provider_exhausted("gemini_flash", message)
            return ConnectorError(f"Gemini 결제 크레딧 소진 — 즉시 폴백: {message}")
        return RateLimitError(message)
    if code in {408, 500, 502, 503, 504}:
        return ConnectorTimeoutError(message)
    if code == 400 and _looks_like_context_error(message):
        return ContextLengthExceeded(message)
    return ConnectorError(message)


def _looks_like_context_error(message: str) -> bool:
    lowered = message.lower()
    return "context" in lowered or "token" in lowered or "too long" in lowered
