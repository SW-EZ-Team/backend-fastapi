"""Gemini 안정화(스로틀·지수 백오프·모델/프로바이더 폴백)·TTS HTTP 경로 단위 테스트.

시연 중 503/429 폭주 대응으로 추가된 동작을 오프라인으로 검증한다:
- GEMINI_REQUEST_INTERVAL_MS 호출 시작 간격 스로틀
- GEMINI_TEXT_RETRY_* 지수 백오프 1s→2s→4s→8s
- GEMINI_TEXT_MODEL_FALLBACKS 모델 폴백 순서
- GEMINI_TEXT_TIMEOUT_MS 타임아웃 매핑
- 프로바이더 폴백 체인의 AuthError 영구 제외
- QWEN3_TTS_MODAL_URL HTTP 경로 (httpx mock)
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import ClassVar

import httpx
import pytest
from google.genai import errors as genai_errors

from ai_connectors import _gemini_throttle as throttle
from ai_connectors._failover_text import FailoverAIConnector
from ai_connectors.errors import (
    AuthError,
    InferenceError,
    RateLimitError,
    ServiceUnavailableError,
)
from ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from ai_connectors.text import gemini_connector as root_gemini
from ai_connectors.text_schemas import ChapterAIRequest, ChapterAIResponse
from ai_connectors.tts import qwen3_tts_modal_connector as tts_modal
from ai_connectors.tts_schemas import TTSRequest


@pytest.fixture(autouse=True)
def stabilization_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """테스트 기본값: 스로틀/백오프 대기 0, 단일 모델 체인, 스로틀 상태 초기화."""
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "0")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_ATTEMPTS", "3")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_INITIAL_MS", "0")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_MAX_MS", "0")
    monkeypatch.setenv("GEMINI_TEXT_TIMEOUT_MS", "120000")
    monkeypatch.setenv("GEMINI_TEXT_MODEL_FALLBACKS", "gemini-test")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")
    throttle.reset_throttle()


# ── 스로틀 ────────────────────────────────────────────────────────────────


def test_throttle_reserves_interval_between_call_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2000ms 간격이면 연속 예약 대기시간이 0 → 2.0 → 4.0초로 늘어난다."""
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "2000")
    monkeypatch.setattr(throttle.time, "monotonic", lambda: 100.0)
    throttle.reset_throttle()

    assert throttle._reserve_slot() == pytest.approx(0.0)
    assert throttle._reserve_slot() == pytest.approx(2.0)
    assert throttle._reserve_slot() == pytest.approx(4.0)


def test_throttle_noop_when_interval_zero_or_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0 또는 미설정이면 스로틀은 항상 0초(no-op)다."""
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "0")
    throttle.reset_throttle()
    assert throttle._reserve_slot() == 0.0

    monkeypatch.delenv("GEMINI_REQUEST_INTERVAL_MS", raising=False)
    assert throttle._reserve_slot() == 0.0


def test_throttle_malformed_or_negative_interval_disables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비정수("abc")·음수 간격은 기본값 0(비활성)으로 복구된다."""
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "abc")
    throttle.reset_throttle()
    assert throttle.request_interval_sec() == 0.0
    assert throttle._reserve_slot() == 0.0

    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "-500")
    assert throttle.request_interval_sec() == 0.0


def test_throttle_huge_interval_clamped_to_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """오설정된 거대 간격(999999999999ms)은 상한 60초로 잘려 사실상 무한 대기를 막는다."""
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "999999999999")
    throttle.reset_throttle()
    assert throttle.request_interval_sec() == 60.0


def test_throttle_concurrent_first_calls_serialize_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """동시 첫 호출(thundering herd)도 락으로 직렬 예약돼 슬롯이 겹치지 않는다."""
    import threading

    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "1000")
    monkeypatch.setattr(throttle.time, "monotonic", lambda: 100.0)
    throttle.reset_throttle()

    delays: list[float] = []
    lock = threading.Lock()

    def reserve() -> None:
        delay = throttle._reserve_slot()
        with lock:
            delays.append(delay)

    threads = [threading.Thread(target=reserve) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 시계가 고정돼 있으므로 예약 지연은 0,1,2,...,7초가 정확히 한 번씩 나와야 한다.
    assert sorted(delays) == [float(n) for n in range(8)]


# ── 백오프 정책 ───────────────────────────────────────────────────────────


def test_backoff_schedule_doubles_and_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    """1000ms 초기·8000ms 상한이면 지연이 1→2→4→8→8초로 진행된다."""
    monkeypatch.setenv("GEMINI_TEXT_RETRY_INITIAL_MS", "1000")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_MAX_MS", "8000")
    delays = [throttle.backoff_delay_sec(attempt) for attempt in range(5)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_retry_attempts_default_and_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본 5회, 잘못된 값은 기본값, 과도한 값은 10으로 보정된다."""
    monkeypatch.delenv("GEMINI_TEXT_RETRY_ATTEMPTS", raising=False)
    assert throttle.retry_attempts() == 5
    monkeypatch.setenv("GEMINI_TEXT_RETRY_ATTEMPTS", "abc")
    assert throttle.retry_attempts() == 5
    monkeypatch.setenv("GEMINI_TEXT_RETRY_ATTEMPTS", "99")
    assert throttle.retry_attempts() == 10


def test_model_chain_preserves_order_and_dedups_primary() -> None:
    """현재 모델이 선두, 폴백 목록 순서 보존, 중복 제거."""
    chain = throttle.model_chain("gemini-3.5-flash")
    assert chain[0] == "gemini-3.5-flash"


def test_model_chain_env_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_TEXT_MODEL_FALLBACKS", "m1, m2 ,m3")
    assert throttle.model_chain("m1") == ["m1", "m2", "m3"]
    assert throttle.model_chain("m2") == ["m2", "m1", "m3"]
    assert throttle.model_chain("other") == ["other", "m1", "m2", "m3"]


# ── 루트 Gemini 커넥터: 백오프·모델 폴백·타임아웃 ─────────────────────────


@dataclass
class _Call:
    model: str
    contents: str


class _FakeModels:
    def __init__(self, owner: "_FakeClient") -> None:
        self._owner = owner

    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        self._owner.calls.append(_Call(model=model, contents=contents))
        if _FakeClient.errors:
            raise _FakeClient.errors.pop(0)
        if _FakeClient.sync_delay_sec > 0:
            time.sleep(_FakeClient.sync_delay_sec)

        class _Resp:
            text = "본문"
            usage_metadata = None
            candidates: list[object] = []

        return _Resp()


class _FakeClient:
    last: ClassVar["_FakeClient | None"] = None
    errors: ClassVar[list[BaseException]] = []
    sync_delay_sec: ClassVar[float] = 0.0

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.calls: list[_Call] = []
        self.models = _FakeModels(self)
        _FakeClient.last = self

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def reset_fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.last = None
    _FakeClient.errors = []
    _FakeClient.sync_delay_sec = 0.0
    monkeypatch.setattr(root_gemini.genai, "Client", _FakeClient)


def _req() -> ChapterAIRequest:
    return ChapterAIRequest(system="시스템", user="사용자", max_tokens=64, temperature=0.1)


async def test_backoff_sequence_1_2_4_8(monkeypatch: pytest.MonkeyPatch) -> None:
    """5회 연속 429면 백오프 1/2/4/8초 후 RateLimitError 가 올라온다."""
    monkeypatch.setenv("GEMINI_TEXT_RETRY_ATTEMPTS", "5")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_INITIAL_MS", "1000")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_MAX_MS", "8000")
    recorded: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    _FakeClient.errors = [
        genai_errors.ClientError(429, {"error": {"message": "quota"}}) for _ in range(5)
    ]

    connector = root_gemini.GeminiGenAIConnector()
    with pytest.raises(RateLimitError):
        await connector.generate(_req())

    assert recorded == [1.0, 2.0, 4.0, 8.0]
    assert _FakeClient.last is not None
    assert len(_FakeClient.last.calls) == 5


async def test_model_fallback_order_on_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """모델당 재시도 소진 시 폴백 목록 순서대로 다음 모델을 시도한다."""
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "m1")
    monkeypatch.setenv("GEMINI_TEXT_MODEL_FALLBACKS", "m1,m2,m3")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_ATTEMPTS", "1")
    _FakeClient.errors = [
        genai_errors.ServerError(503, {"error": {"message": "overloaded"}}),
        genai_errors.ServerError(503, {"error": {"message": "overloaded"}}),
    ]

    connector = root_gemini.GeminiGenAIConnector()
    response = await connector.generate(_req())

    assert _FakeClient.last is not None
    assert [call.model for call in _FakeClient.last.calls] == ["m1", "m2", "m3"]
    assert response.model == "m3"
    assert response.text == "본문"


async def test_all_models_exhausted_raises_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """모든 모델이 503이면 마지막 오류(ServiceUnavailableError)가 올라온다."""
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "m1")
    monkeypatch.setenv("GEMINI_TEXT_MODEL_FALLBACKS", "m1,m2")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_ATTEMPTS", "1")
    _FakeClient.errors = [
        genai_errors.ServerError(503, {"error": {"message": "overloaded"}})
        for _ in range(2)
    ]

    connector = root_gemini.GeminiGenAIConnector()
    with pytest.raises(ServiceUnavailableError):
        await connector.generate(_req())


async def test_timeout_maps_to_connector_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK 호출이 GEMINI_TEXT_TIMEOUT_MS 를 넘기면 TimeoutError 로 매핑된다."""
    monkeypatch.setenv("GEMINI_TEXT_TIMEOUT_MS", "50")
    monkeypatch.setenv("GEMINI_TEXT_RETRY_ATTEMPTS", "1")
    _FakeClient.sync_delay_sec = 0.3

    connector = root_gemini.GeminiGenAIConnector()
    with pytest.raises(ConnectorTimeoutError):
        await connector.generate(_req())


def test_map_api_error_distinguishes_503() -> None:
    """503/UNAVAILABLE 은 ServiceUnavailableError, 500 은 TimeoutError 로 매핑된다."""
    err_503 = root_gemini._map_api_error(
        genai_errors.ServerError(503, {"error": {"message": "model overloaded"}})
    )
    assert isinstance(err_503, ServiceUnavailableError)
    err_500 = root_gemini._map_api_error(
        genai_errors.ServerError(500, {"error": {"message": "boom"}})
    )
    assert isinstance(err_500, ConnectorTimeoutError)


# ── 프로바이더 폴백 체인 (AuthError 영구 제외) ────────────────────────────


class _StubConnector:
    """generate 호출 횟수를 기록하는 테스트용 커넥터."""

    def __init__(self, name: str, error: Exception | None = None) -> None:
        self.name = name
        self.error = error
        self.call_count = 0

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        self.call_count += 1
        if self.error is not None:
            raise self.error
        return ChapterAIResponse(
            text=f"{self.name} 응답",
            model=self.name,
            input_tokens=1,
            output_tokens=1,
            finish_reason="stop",
        )

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return False


async def test_provider_chain_skips_auth_error_fallback_permanently() -> None:
    """폴백1이 AuthError(무효 키)면 영구 제외하고 폴백2가 응답한다."""
    primary = _StubConnector("gemini", error=RateLimitError("429"))
    bad_openai = _StubConnector("openai", error=AuthError("invalid key"))
    good_claude = _StubConnector("claude", error=None)
    chain = FailoverAIConnector(
        primary=primary,
        fallback_factories=[lambda: bad_openai, lambda: good_claude],
        name="test_chain",
        failure_threshold=1,
    )

    response = await chain.generate(_req())
    assert response.text == "claude 응답"
    assert bad_openai.call_count == 1

    # 두 번째 요청에서는 AuthError 폴백을 다시 호출하지 않는다(영구 제외)
    response2 = await chain.generate(_req())
    assert response2.text == "claude 응답"
    assert bad_openai.call_count == 1
    assert good_claude.call_count == 2


async def test_provider_chain_skips_auth_error_at_construction() -> None:
    """팩토리 생성 단계 AuthError 도 영구 제외 후 다음 폴백으로 진행한다."""
    primary = _StubConnector("gemini", error=RateLimitError("429"))
    created: list[str] = []

    def _bad_factory() -> object:
        created.append("bad")
        raise AuthError("키 미설정")

    good = _StubConnector("claude", error=None)
    chain = FailoverAIConnector(
        primary=primary,
        fallback_factories=[_bad_factory, lambda: good],
        name="test_chain",
        failure_threshold=1,
    )

    response = await chain.generate(_req())
    assert response.text == "claude 응답"
    await chain.generate(_req())
    # 영구 제외 후에는 실패 팩토리를 다시 호출하지 않는다
    assert created == ["bad"]


async def test_provider_chain_single_factory_backward_compat() -> None:
    """기존 단일 fallback_factory 시그니처가 그대로 동작한다."""
    primary = _StubConnector("gemini", error=RateLimitError("429"))
    fallback = _StubConnector("openai", error=None)
    chain = FailoverAIConnector(
        primary=primary,
        fallback_factory=lambda: fallback,
        name="legacy",
        failure_threshold=1,
    )
    response = await chain.generate(_req())
    assert response.text == "openai 응답"
    assert chain.fallback_name == "openai"


# ── 주 커넥터 복귀(recovery) ──────────────────────────────────────────────


def _patch_failover_clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    """_failover_text 모듈의 monotonic을 가짜 시계로 바꾼다."""
    from ai_connectors import _failover_text

    clock = {"now": 1000.0}
    monkeypatch.setattr(_failover_text.time, "monotonic", lambda: clock["now"])
    return clock


async def test_failover_recovers_primary_after_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """폴백 전환 후 복귀 간격이 지나면 주 커넥터를 재시도해 회로를 닫는다."""
    monkeypatch.setenv("TEXT_FALLBACK_RECOVERY_SEC", "60")
    clock = _patch_failover_clock(monkeypatch)

    primary = _StubConnector("gemini", error=RateLimitError("429"))
    fallback = _StubConnector("openai", error=None)
    chain = FailoverAIConnector(
        primary=primary,
        fallback_factories=[lambda: fallback],
        name="recovery_chain",
        failure_threshold=1,
    )

    # 1차: 주 실패 → 폴백 전환
    response = await chain.generate(_req())
    assert response.text == "openai 응답"
    assert chain.fallback_active is True

    # 간격 도달 전에는 주 커넥터를 다시 호출하지 않는다
    clock["now"] += 30.0
    await chain.generate(_req())
    assert primary.call_count == 1

    # 간격 경과 + 주 커넥터 회복 → 복귀 성공, 회로 닫힘
    primary.error = None
    clock["now"] += 31.0
    response = await chain.generate(_req())
    assert response.text == "gemini 응답"
    assert chain.fallback_active is False
    assert chain.failure_count == 0

    # 복귀 후에는 주 커넥터가 계속 응답한다
    response = await chain.generate(_req())
    assert response.text == "gemini 응답"


async def test_failover_probe_failure_stays_on_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """복귀 시도가 실패하면 폴백을 유지하고 다음 시도를 간격만큼 미룬다."""
    monkeypatch.setenv("TEXT_FALLBACK_RECOVERY_SEC", "60")
    clock = _patch_failover_clock(monkeypatch)

    primary = _StubConnector("gemini", error=RateLimitError("429"))
    fallback = _StubConnector("openai", error=None)
    chain = FailoverAIConnector(
        primary=primary,
        fallback_factories=[lambda: fallback],
        name="recovery_chain",
        failure_threshold=1,
    )

    await chain.generate(_req())  # 폴백 전환 (주 1회 호출)
    clock["now"] += 61.0
    response = await chain.generate(_req())  # 복귀 시도 실패 → 폴백 응답
    assert response.text == "openai 응답"
    assert chain.fallback_active is True
    assert primary.call_count == 2

    # 새 간격이 지나기 전에는 다시 시도하지 않는다
    clock["now"] += 30.0
    await chain.generate(_req())
    assert primary.call_count == 2


async def test_failover_recovery_disabled_when_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TEXT_FALLBACK_RECOVERY_SEC=0이면 기존 영구 폴백 동작을 유지한다."""
    monkeypatch.setenv("TEXT_FALLBACK_RECOVERY_SEC", "0")
    clock = _patch_failover_clock(monkeypatch)

    primary = _StubConnector("gemini", error=RateLimitError("429"))
    fallback = _StubConnector("openai", error=None)
    chain = FailoverAIConnector(
        primary=primary,
        fallback_factories=[lambda: fallback],
        name="sticky_chain",
        failure_threshold=1,
    )

    await chain.generate(_req())
    primary.error = None
    clock["now"] += 100_000.0
    response = await chain.generate(_req())
    assert response.text == "openai 응답"
    assert chain.fallback_active is True
    assert primary.call_count == 1


# ── Qwen3-TTS Modal HTTP 경로 ────────────────────────────────────────────


class _FakeHttpClient:
    init_kwargs: ClassVar[list[dict[str, object]]] = []
    last_post: ClassVar[dict[str, object] | None] = None
    response: ClassVar[httpx.Response | None] = None

    def __init__(self, **kwargs: object) -> None:
        _FakeHttpClient.init_kwargs.append(kwargs)

    async def __aenter__(self) -> "_FakeHttpClient":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def post(
        self,
        url: str,
        data: dict[str, str] | None = None,
        files: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        _FakeHttpClient.last_post = {
            "url": url,
            "data": data,
            "files": files,
            "headers": headers,
        }
        assert _FakeHttpClient.response is not None
        return _FakeHttpClient.response


@pytest.fixture()
def patch_tts_http(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeHttpClient.init_kwargs = []
    _FakeHttpClient.last_post = None
    _FakeHttpClient.response = None
    monkeypatch.setattr(tts_modal.httpx, "AsyncClient", _FakeHttpClient)
    monkeypatch.setenv("QWEN3_TTS_MODAL_URL", "https://example.modal.run/synthesize")
    monkeypatch.setenv("QWEN3_TTS_MODAL_TOKEN", "tts-token")


def _tts_request() -> TTSRequest:
    return TTSRequest(
        text="안녕하세요",
        ref_audio_bytes=b"\x00\x01\x02\x03",
        ref_text="레퍼런스",
        language="auto",
        speed=1.0,
    )


async def test_tts_http_path_success(patch_tts_http: None) -> None:
    """URL 설정 시 multipart POST 후 WAV 바디·헤더를 TTSResponse 로 변환한다."""
    _FakeHttpClient.response = httpx.Response(
        200,
        content=b"RIFF-fake-wav",
        headers={
            "x-sample-rate": "24000",
            "x-duration-sec": "1.250",
            "x-latency-ms": "321.5",
            "x-char-count": "5",
            "x-ref-text-used": "%EB%A0%88%ED%8D%BC%EB%9F%B0%EC%8A%A4",
            "x-ref-text-source": "client",
        },
        request=httpx.Request("POST", "https://example.modal.run/synthesize"),
    )

    connector = tts_modal.Qwen3TTSModalConnector()
    response = await connector.synthesize(_tts_request())

    assert response.audio_bytes == b"RIFF-fake-wav"
    assert response.sample_rate == 24000
    assert response.duration_sec == pytest.approx(1.25)
    assert response.resolved_ref_text == "레퍼런스"
    # follow_redirects=True 로 303 리다이렉트를 흡수한다
    assert _FakeHttpClient.init_kwargs[0].get("follow_redirects") is True
    assert _FakeHttpClient.last_post is not None
    assert _FakeHttpClient.last_post["data"]["text"] == "안녕하세요"
    assert _FakeHttpClient.last_post["headers"]["Authorization"] == "Bearer tts-token"


async def test_tts_http_path_non_2xx_maps_to_inference_error(
    patch_tts_http: None,
) -> None:
    """비 2xx 응답은 InferenceError 계열로 정규화된다."""
    _FakeHttpClient.response = httpx.Response(
        500,
        content=b"internal error",
        request=httpx.Request("POST", "https://example.modal.run/synthesize"),
    )

    connector = tts_modal.Qwen3TTSModalConnector()
    with pytest.raises(InferenceError):
        await connector._call_endpoint(_tts_request())


async def test_tts_http_path_auth_error_no_retry(patch_tts_http: None) -> None:
    """401 은 AuthError — _modal_retry 의 재시도 제외 대상으로 즉시 올라온다."""
    _FakeHttpClient.response = httpx.Response(
        401,
        content=b"invalid token",
        request=httpx.Request("POST", "https://example.modal.run/synthesize"),
    )

    connector = tts_modal.Qwen3TTSModalConnector()
    with pytest.raises(AuthError):
        await connector.synthesize(_tts_request())
    # call_with_retry 가 AuthError 를 재시도하지 않아 POST 는 1회만 발생한다
    assert len(_FakeHttpClient.init_kwargs) == 1


def test_tts_sdk_path_remains_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """QWEN3_TTS_MODAL_URL 미설정이면 HTTP 경로가 비활성(기존 SDK 경로)이다."""
    monkeypatch.delenv("QWEN3_TTS_MODAL_URL", raising=False)
    connector = tts_modal.Qwen3TTSModalConnector()
    assert connector._http_url == ""
