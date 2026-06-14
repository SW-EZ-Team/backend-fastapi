"""[백로그 #1] 타임아웃 다발 시 실제 동시 SDK 호출 상한 강제 단위 테스트.

기존 구조 결함: _call_sdk 가 asyncio.wait_for(asyncio.to_thread(blocking SDK)) 였다.
wait_for 가 타임아웃하면 awaiting 코루틴만 풀리고 async with semaphore 가 즉시 풀려
세마포어 슬롯이 반환되지만, blocking SDK 호출은 기본 executor 스레드에서 계속 돈다.
→ 세마포어 "동시성 3" 밖에서 실 SDK 호출이 누적될 수 있다.

해결: blocking 호출을 크기 제한된 전용 ThreadPoolExecutor(워커 수 =
EXAMFORGE_GEMINI_CONCURRENCY)로만 실행한다. 타임아웃으로 누수된(아직 도는) 호출도
워커를 계속 점유하므로, *실제 동시에 살아있는 SDK 호출 수*가 워커 수를 넘지 못한다.

이 테스트는 타임아웃을 다발로 유발한 뒤, 동시에 활성인 가짜 SDK 호출의 피크가
워커 상한 이하로 유지되는지 검증한다. 데드락 없이 모든 호출이 종료되는지도 확인한다.
실 Gemini/네트워크 호출은 전혀 없다(가짜 _generate_sync 로 치환).
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.modules.ExamForge_V1.common import _connector_gemini_genai as gemini_genai


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """각 테스트 전후로 세마포어·executor 캐시를 초기화한다(동시성 env 반영 위해)."""
    gemini_genai.reset_examforge_genai_semaphore()
    gemini_genai.reset_examforge_sdk_executor()
    yield
    gemini_genai.reset_examforge_genai_semaphore()
    gemini_genai.reset_examforge_sdk_executor()


class _ConcurrencyTracker:
    """가짜 blocking SDK 호출의 동시 활성 수 피크를 스레드 안전하게 추적한다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.started = 0

    def enter(self) -> None:
        with self._lock:
            self.active += 1
            self.started += 1
            self.peak = max(self.peak, self.active)

    def exit(self) -> None:
        with self._lock:
            self.active -= 1


def _make_fake_connector(
    monkeypatch: pytest.MonkeyPatch,
    tracker: _ConcurrencyTracker,
    work_sec: float,
) -> gemini_genai.GeminiGenAIConnector:
    """가짜 SDK 클라이언트로 커넥터를 만들고 _generate_sync 를 blocking 추적 함수로 치환한다."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    # genai.Client 가 실제로 키 검증/네트워크를 타지 않도록 가짜로 교체한다.
    class _FakeClient:
        def __init__(self, *_a, **_k) -> None:
            self.models = object()

    monkeypatch.setattr(gemini_genai.genai, "Client", _FakeClient)
    connector = gemini_genai.GeminiGenAIConnector()

    def _fake_generate_sync(req: object, model: str | None = None) -> object:
        """실 SDK 대신 work_sec 동안 blocking sleep — 동시 활성 수를 추적한다."""
        tracker.enter()
        try:
            time.sleep(work_sec)
        finally:
            tracker.exit()
        # _to_response 가 파싱할 최소 형태의 가짜 응답.
        return _FakeResponse()

    monkeypatch.setattr(connector, "_generate_sync", _fake_generate_sync)
    return connector


class _FakeUsage:
    prompt_token_count = 10
    candidates_token_count = 20


class _FakeResponse:
    text = '{"questions": []}'
    usage_metadata = _FakeUsage()
    candidates: list = []


async def test_timeout_storm_keeps_active_sdk_calls_under_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """타임아웃 다발 상황에서도 동시 활성 SDK 호출 피크가 워커 상한 이하로 유지된다.

    핵심 회귀 방어: 기존 asyncio.to_thread 구조였다면 타임아웃으로 코루틴이 풀린 뒤
    다음 호출이 곧바로 새 스레드를 잡아 활성 수가 상한을 크게 넘었다. bounded
    executor 는 워커 수를 고정해 누수 호출까지 포함한 실제 동시성을 캡한다.
    """
    concurrency = 2
    monkeypatch.setenv("EXAMFORGE_GEMINI_CONCURRENCY", str(concurrency))
    # 재시도/모델 폴백을 끄고(시도 1회, 폴백 없음) 백오프 대기도 0으로 — 테스트를 빠르게.
    monkeypatch.setenv("GEMINI_TEXT_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")
    monkeypatch.setenv("GEMINI_TEXT_MODEL_FALLBACKS", "gemini-test")
    # 스로틀 간격 0(대기 없이 즉시) — 동시성 검증에 간격 변수를 끼우지 않는다.
    monkeypatch.setenv("EXAMFORGE_GEMINI_INTERVAL_MS", "0")
    # 타임아웃을 가짜 작업시간(0.5s)보다 훨씬 짧게(50ms) — 모든 호출이 타임아웃한다.
    monkeypatch.setenv("GEMINI_TEXT_TIMEOUT_MS", "50")

    tracker = _ConcurrencyTracker()
    connector = _make_fake_connector(monkeypatch, tracker, work_sec=0.5)

    req = gemini_genai.ChapterAIRequest(
        system="sys", user="문항 생성", max_tokens=256, temperature=0.5
    )

    # 워커 수보다 훨씬 많은 호출을 동시에 던진다. 전부 타임아웃할 것이다.
    n_calls = 12

    async def _one() -> None:
        with pytest.raises(gemini_genai.ConnectorTimeoutError):
            await connector.generate(req)

    await asyncio.gather(*[_one() for _ in range(n_calls)])

    # 타임아웃으로 누수된 blocking 호출이 아직 워커에서 돌고 있고, 큐에는 나머지
    # 제출이 대기 중이다. executor 가 워커 수(=concurrency)만큼만 동시에 처리하며
    # 큐를 순차적으로 비울 때까지 폴링한다(데드락이면 여기서 타임아웃으로 실패).
    # 큐 처리 시간 = ceil(n_calls / concurrency) * work_sec ≈ 6 * 0.5 = 3.0s.
    deadline = time.monotonic() + 8.0
    while tracker.started < n_calls and time.monotonic() < deadline:
        await asyncio.sleep(0.05)

    # 핵심 단언: 동시에 활성이던 SDK 호출 피크가 워커 상한을 넘지 않는다.
    # 기존 asyncio.to_thread 구조였다면 타임아웃 직후 다음 호출이 새 스레드를 잡아
    # 활성 수가 상한을 크게 넘었다(피크 >> concurrency). bounded executor 가 이를 막는다.
    assert tracker.peak <= concurrency, (
        f"동시 활성 SDK 호출 피크 {tracker.peak} 가 상한 {concurrency} 초과 — "
        "bounded executor 가 누수 호출을 막지 못함"
    )
    # 모든 제출이 결국 실행됐다(큐에서 순차 처리). 즉 유실·데드락 없음.
    assert tracker.started == n_calls, "executor 큐가 끝까지 비워지지 않음(데드락 의심)"

    # 마지막 배치 스레드가 종료될 때까지 잠깐 더 기다려 활성 0 수렴을 확인한다.
    drain_deadline = time.monotonic() + 2.0
    while tracker.active > 0 and time.monotonic() < drain_deadline:
        await asyncio.sleep(0.05)
    assert tracker.active == 0


async def test_no_timeout_path_returns_response_and_respects_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """타임아웃이 없을 때도 정상 응답을 돌려주고 동시성 상한을 지킨다(데드락 없음)."""
    concurrency = 3
    monkeypatch.setenv("EXAMFORGE_GEMINI_CONCURRENCY", str(concurrency))
    monkeypatch.setenv("GEMINI_TEXT_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")
    monkeypatch.setenv("GEMINI_TEXT_MODEL_FALLBACKS", "gemini-test")
    monkeypatch.setenv("EXAMFORGE_GEMINI_INTERVAL_MS", "0")
    # 타임아웃을 작업시간(50ms)보다 넉넉히(5s) 두면 전부 정상 완료한다.
    monkeypatch.setenv("GEMINI_TEXT_TIMEOUT_MS", "5000")

    tracker = _ConcurrencyTracker()
    connector = _make_fake_connector(monkeypatch, tracker, work_sec=0.05)

    req = gemini_genai.ChapterAIRequest(
        system="sys", user="문항 생성", max_tokens=256, temperature=0.5
    )

    n_calls = 9
    results = await asyncio.gather(*[connector.generate(req) for _ in range(n_calls)])

    assert len(results) == n_calls
    assert all(r.text is not None for r in results)
    # 정상 경로에서도 동시 활성 호출이 워커 상한을 넘지 않는다.
    assert tracker.peak <= concurrency
    assert tracker.started == n_calls
    assert tracker.active == 0


def test_sdk_executor_worker_count_matches_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전용 executor 의 워커 수가 EXAMFORGE_GEMINI_CONCURRENCY 와 일치한다."""
    monkeypatch.setenv("EXAMFORGE_GEMINI_CONCURRENCY", "4")
    gemini_genai.reset_examforge_sdk_executor()
    executor = gemini_genai._get_examforge_sdk_executor()
    assert executor._max_workers == 4
