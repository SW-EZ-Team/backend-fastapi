"""ExamForge 전용 Gemini 레인(스로틀·동시성) 격리 단위 테스트.

모의고사 생성 750초 타임아웃 해소를 위해 ExamForge 만 전용 Gemini 레인을
쓰도록 분리했다. 이 테스트는 전용 레인이 전역(채팅·강의) 레인과 완전히
격리되는지, 그리고 전용 환경변수로만 동작이 바뀌는지 검증한다:

- 전용 레인은 EXAMFORGE_GEMINI_INTERVAL_MS 를 읽고 전역 간격과 무관하다.
- 전용 레인 상태(next_allowed_at)는 전역 레인과 독립적이다(상호 오염 없음).
- 전역 레인(인자 없는 기존 호출)은 동작 불변(하위 호환).
- 전용 세마포어는 EXAMFORGE_GEMINI_CONCURRENCY(기본 3)를 따른다.
"""
from __future__ import annotations

import asyncio

import pytest

from ai_connectors import _gemini_throttle as throttle
from app.modules.ExamForge_V1.common import _connector_gemini_genai as gemini_genai
from app.modules.ExamForge_V1.common.config import examforge_gemini_concurrency

_LANE = gemini_genai._EXAMFORGE_THROTTLE_LANE
_INTERVAL_ENV = gemini_genai._EXAMFORGE_INTERVAL_ENV


@pytest.fixture(autouse=True)
def _reset_throttle_state() -> None:
    """각 테스트 전 모든 레인 스로틀 상태와 전용 세마포어 캐시를 초기화한다."""
    throttle.reset_throttle()
    gemini_genai.reset_examforge_genai_semaphore()
    yield
    throttle.reset_throttle()
    gemini_genai.reset_examforge_genai_semaphore()


# ── 전용 레인 간격(interval) ────────────────────────────────────────────


def test_examforge_lane_uses_dedicated_interval_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전용 레인은 EXAMFORGE_GEMINI_INTERVAL_MS 를 읽는다(전역 env 무시)."""
    # 전역은 큰 값(2000ms), 전용은 작은 값(600ms) — 전용 값만 적용돼야 한다.
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "2000")
    monkeypatch.setenv("EXAMFORGE_GEMINI_INTERVAL_MS", "600")
    monkeypatch.setattr(throttle.time, "monotonic", lambda: 100.0)

    # 전용 레인 연속 예약: 0 → 0.6 → 1.2초 (전역 2.0초가 아님)
    assert throttle._reserve_slot(_LANE, _INTERVAL_ENV) == pytest.approx(0.0)
    assert throttle._reserve_slot(_LANE, _INTERVAL_ENV) == pytest.approx(0.6)
    assert throttle._reserve_slot(_LANE, _INTERVAL_ENV) == pytest.approx(1.2)


def test_examforge_lane_isolated_from_global_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전용 레인 슬롯 예약은 전역 레인 next_allowed_at 을 건드리지 않는다."""
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "2000")
    monkeypatch.setenv("EXAMFORGE_GEMINI_INTERVAL_MS", "600")
    monkeypatch.setattr(throttle.time, "monotonic", lambda: 100.0)

    # 전용 레인을 여러 번 예약해도…
    throttle._reserve_slot(_LANE, _INTERVAL_ENV)
    throttle._reserve_slot(_LANE, _INTERVAL_ENV)
    throttle._reserve_slot(_LANE, _INTERVAL_ENV)

    # 전역 레인의 첫 예약은 여전히 0(전용 레인 누적에 오염되지 않음).
    assert throttle._reserve_slot() == pytest.approx(0.0)
    # 전역 레인 두 번째는 전역 간격(2.0초)만큼만 늘어난다.
    assert throttle._reserve_slot() == pytest.approx(2.0)


def test_global_lane_unaffected_by_examforge_reservations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """역방향: 전역 레인을 굴려도 전용 레인 첫 예약은 0(하위 호환·격리)."""
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "2000")
    monkeypatch.setenv("EXAMFORGE_GEMINI_INTERVAL_MS", "600")
    monkeypatch.setattr(throttle.time, "monotonic", lambda: 100.0)

    throttle._reserve_slot()  # 전역 레인 1회
    throttle._reserve_slot()  # 전역 레인 2회

    # 전용 레인 첫 예약은 전역 누적과 무관하게 0이어야 한다.
    assert throttle._reserve_slot(_LANE, _INTERVAL_ENV) == pytest.approx(0.0)


def test_examforge_lane_code_default_600ms_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전용 간격 env 미설정이면 코드 기본값(default_ms=600)이 적용된다(429 방어).

    env 없이도 ExamForge 레인이 동작해야 한다는 요구사항을 검증한다 —
    default_ms 미지정(전역 레인) 0과 대비된다.
    """
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "2000")
    monkeypatch.delenv("EXAMFORGE_GEMINI_INTERVAL_MS", raising=False)
    monkeypatch.setattr(throttle.time, "monotonic", lambda: 100.0)
    default_ms = gemini_genai._EXAMFORGE_INTERVAL_DEFAULT_MS  # 600

    # default_ms 를 넘기면 env 없이도 0 → 0.6초 간격이 생긴다.
    assert throttle._reserve_slot(_LANE, _INTERVAL_ENV, default_ms) == pytest.approx(0.0)
    assert throttle._reserve_slot(_LANE, _INTERVAL_ENV, default_ms) == pytest.approx(0.6)


def test_examforge_lane_explicit_zero_disables_throttle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EXAMFORGE_GEMINI_INTERVAL_MS=0 을 명시하면 코드 기본값을 무시하고 비활성(0초)."""
    monkeypatch.setenv("EXAMFORGE_GEMINI_INTERVAL_MS", "0")
    default_ms = gemini_genai._EXAMFORGE_INTERVAL_DEFAULT_MS
    assert throttle._reserve_slot(_LANE, _INTERVAL_ENV, default_ms) == pytest.approx(0.0)
    assert throttle._reserve_slot(_LANE, _INTERVAL_ENV, default_ms) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_wait_for_slot_lane_kwargs_do_not_touch_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """wait_for_slot(lane=...) 비동기 경로도 전역 레인과 격리된다."""
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_MS", "2000")
    monkeypatch.setenv("EXAMFORGE_GEMINI_INTERVAL_MS", "0")  # 대기 없이 빠르게

    # 전용 레인 대기는 즉시 반환(간격 0). 전역 레인 상태는 그대로.
    await throttle.wait_for_slot(lane=_LANE, interval_env=_INTERVAL_ENV)

    monkeypatch.setattr(throttle.time, "monotonic", lambda: 100.0)
    # 전역 레인 첫 예약은 여전히 0(전용 레인 wait 에 오염 안 됨).
    assert throttle._reserve_slot() == pytest.approx(0.0)


# ── 전용 동시성 세마포어 ─────────────────────────────────────────────────


def test_examforge_concurrency_default_is_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EXAMFORGE_GEMINI_CONCURRENCY 미설정이면 기본 3."""
    monkeypatch.delenv("EXAMFORGE_GEMINI_CONCURRENCY", raising=False)
    assert examforge_gemini_concurrency() == 3


def test_examforge_concurrency_override_and_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env 오버라이드가 반영되고, 0 이하/잘못된 값은 최소 1로 보정된다."""
    monkeypatch.setenv("EXAMFORGE_GEMINI_CONCURRENCY", "5")
    assert examforge_gemini_concurrency() == 5
    monkeypatch.setenv("EXAMFORGE_GEMINI_CONCURRENCY", "0")
    assert examforge_gemini_concurrency() == 1
    monkeypatch.setenv("EXAMFORGE_GEMINI_CONCURRENCY", "abc")
    assert examforge_gemini_concurrency() == 3  # 파싱 실패 → 기본값


def test_examforge_semaphore_uses_dedicated_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전용 세마포어 슬롯 수는 EXAMFORGE_GEMINI_CONCURRENCY 를 따른다.

    전역 GEMINI_TEXT_MAX_CONCURRENCY=1 이어도 전용 세마포어는 3 슬롯을 연다 —
    이게 핵심: ExamForge 가 전역 동시성 1에 묶이지 않는다.
    """
    monkeypatch.setenv("GEMINI_TEXT_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("EXAMFORGE_GEMINI_CONCURRENCY", "3")
    gemini_genai.reset_examforge_genai_semaphore()

    semaphore = gemini_genai._get_examforge_genai_semaphore()
    # asyncio.Semaphore 는 내부 _value 로 가용 슬롯을 노출한다.
    # 전역 동시성이 1이어도 전용 세마포어는 3 슬롯을 연다.
    assert isinstance(semaphore, asyncio.Semaphore)
    assert semaphore._value == 3


# ── 커넥터 배선(connector-level wiring) ───────────────────────────────────


class _FakeUsage:
    prompt_token_count = 10
    candidates_token_count = 20


class _FakeResponse:
    text = '{"questions": []}'
    usage_metadata = _FakeUsage()
    candidates: list = []


class _FakeModels:
    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        return _FakeResponse()


class _FakeClient:
    def __init__(self, *_args, **_kwargs) -> None:
        self.models = _FakeModels()


@pytest.mark.asyncio
async def test_connector_generate_uses_examforge_lane_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GeminiGenAIConnector.generate 가 실제로 전용 레인 인자로 wait_for_slot 을 부른다.

    이게 깨지면 ExamForge 호출이 조용히 전역(채팅·강의) 레인으로 되돌아가
    2000ms 직렬화에 다시 굶는다 — 레인 분리의 핵심 회귀 방어다.
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")
    monkeypatch.setenv("GEMINI_TEXT_MODEL_FALLBACKS", "gemini-test")
    # SDK 클라이언트는 가짜로 교체(실 네트워크 호출 차단).
    monkeypatch.setattr(gemini_genai.genai, "Client", _FakeClient)

    captured: list[dict] = []

    async def _fake_wait_for_slot(**kwargs) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(gemini_genai._throttle, "wait_for_slot", _fake_wait_for_slot)

    connector = gemini_genai.GeminiGenAIConnector()
    req = gemini_genai.ChapterAIRequest(
        system="sys", user="문항을 생성하라", max_tokens=512, temperature=0.7
    )
    await connector.generate(req)

    assert captured, "wait_for_slot 이 호출되지 않았다."
    call = captured[0]
    assert call.get("lane") == gemini_genai._EXAMFORGE_THROTTLE_LANE
    assert call.get("interval_env") == gemini_genai._EXAMFORGE_INTERVAL_ENV
    assert call.get("default_ms") == gemini_genai._EXAMFORGE_INTERVAL_DEFAULT_MS
