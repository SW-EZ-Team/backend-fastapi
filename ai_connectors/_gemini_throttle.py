"""Gemini 호출 안정화 공통 정책 (시연 503/429 대응).

프로세스 전역 스로틀(호출 시작 간 최소 간격)과 지수 백오프·타임아웃·모델 폴백
체인 환경변수를 한곳에서만 읽는다. 루트 gemini_connector 뿐 아니라
ExamForge/ChapterStudio 의 자체 genai 커넥터도 이 모듈을 공유한다.

- GEMINI_REQUEST_INTERVAL_MS : 호출 시작 간 최소 간격(ms). 0/미설정이면 비활성.
- GEMINI_TEXT_RETRY_ATTEMPTS : 모델당 시도 횟수(기본 5).
- GEMINI_TEXT_RETRY_INITIAL_MS / GEMINI_TEXT_RETRY_MAX_MS : 백오프 1s→2s→4s→8s.
- GEMINI_TEXT_TIMEOUT_MS     : 단일 SDK 호출 타임아웃(기본 120000ms).
- GEMINI_TEXT_MODEL_FALLBACKS: Gemini 내부 모델 폴백 순서(쉼표 구분).

스레드 안전: 상태는 threading.Lock 으로 보호하고 time.monotonic 기준으로
다음 허용 시각을 예약한다. 이벤트 루프가 여러 개여도(테스트 등) 동작한다.
환경변수는 호출 시마다 다시 읽는다(테스트에서 monkeypatch 가능).

## 레인(lane) 분리

채팅·강의 같은 latency 민감 경로(전역 레인)와 ExamForge 같은 배치 대량 호출
경로가 같은 스로틀 상태를 공유하면 한쪽이 다른 쪽을 굶긴다. 그래서 스로틀
상태를 **레인 이름별**로 분리한다(각 레인은 독립 lock + next_allowed_at).
- 전역 레인(lane=None): 기존 GEMINI_REQUEST_INTERVAL_MS 를 그대로 읽는다.
  기존 호출자(루트 gemini_connector 등)는 인자 없이 호출하므로 동작 불변.
- 명명 레인(lane="examforge" 등): 호출자가 interval_env 로 전용 간격 환경변수를
  지정하면 그 값을 읽고, 전역 레인 상태와 완전히 격리된 슬롯 예약을 한다.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time

_DEFAULT_RETRY_ATTEMPTS = 5
_DEFAULT_RETRY_INITIAL_MS = 1000
_DEFAULT_RETRY_MAX_MS = 8000
_DEFAULT_TIMEOUT_MS = 120000
_DEFAULT_MODEL_FALLBACKS = "gemini-3.5-flash,gemini-3.1-flash,gemini-2.5-flash"

# 전역(기본) 스로틀 레인 식별자 — GEMINI_REQUEST_INTERVAL_MS 를 읽는 레인이다.
_GLOBAL_LANE = "__global__"

# 레인별 스로틀 상태 레지스트리.
# 각 레인은 (lock, next_allowed_at) 한 쌍을 독립적으로 보유한다.
# _registry_lock 은 레인 dict 자체의 동시 생성을 보호한다(레인별 lock 과는 별개).
_registry_lock = threading.Lock()
_lane_locks: dict[str, threading.Lock] = {_GLOBAL_LANE: threading.Lock()}
_lane_next_allowed_at: dict[str, float] = {_GLOBAL_LANE: 0.0}

# 하위 호환: 기존 코드/테스트가 직접 참조하던 전역 상태 별칭.
# 전역 레인의 lock 을 그대로 노출한다(테스트가 throttle._state_lock 을 쓰는 경우 대비).
_state_lock = _lane_locks[_GLOBAL_LANE]


def _env_int(name: str, default: int) -> int:
    """환경변수 정수 파싱. 실패하면 기본값으로 복구한다."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


# 스로틀 간격 상한(ms) — 오설정된 거대값(예: 999999999999)이 사실상 무한 대기
# (요청 행 hang)를 만드는 것을 막는다. 정상 사용 범위는 수백 ms~수 초 수준이다.
_MAX_INTERVAL_MS = 60_000


def request_interval_sec(
    interval_env: str = "GEMINI_REQUEST_INTERVAL_MS",
    default_ms: int = 0,
) -> float:
    """Gemini 호출 시작 간 최소 간격(초).

    interval_env 가 가리키는 환경변수에서 ms 값을 읽는다(기본 전역
    GEMINI_REQUEST_INTERVAL_MS). 미설정/파싱 실패면 default_ms 를 쓴다 —
    전역 레인은 default_ms=0(비활성, 기존 동작), ExamForge 전용 레인은
    default_ms=600 을 넘겨 env 없이도 코드 기본값으로 동작한다.
    값이 0 이하면 0(비활성), 양수면 상한 60초로 캡한다.
    """
    interval_ms = _env_int(interval_env, default_ms)
    if interval_ms <= 0:
        return 0.0
    return min(interval_ms, _MAX_INTERVAL_MS) / 1000.0


def _lane_state(lane: str) -> tuple[threading.Lock, str]:
    """레인 이름에 대응하는 lock 을 반환한다(없으면 생성). 레인 키도 함께 돌려준다."""
    with _registry_lock:
        lock = _lane_locks.get(lane)
        if lock is None:
            lock = threading.Lock()
            _lane_locks[lane] = lock
            _lane_next_allowed_at[lane] = 0.0
        return lock, lane


def _reserve_slot(
    lane: str = _GLOBAL_LANE,
    interval_env: str = "GEMINI_REQUEST_INTERVAL_MS",
    default_ms: int = 0,
) -> float:
    """지정 레인의 다음 호출 슬롯을 예약하고 대기 시간(초)을 반환한다.

    레인별 독립 lock + next_allowed_at 으로 다른 레인의 슬롯 예약과 격리된다.
    default_ms 는 env 미설정 시 적용할 코드 기본 간격(ms)이다.
    """
    interval = request_interval_sec(interval_env, default_ms)
    if interval <= 0.0:
        return 0.0
    lock, key = _lane_state(lane)
    with lock:
        now = time.monotonic()
        start_at = max(now, _lane_next_allowed_at.get(key, 0.0))
        _lane_next_allowed_at[key] = start_at + interval
        return start_at - now


async def wait_for_slot(
    *,
    lane: str = _GLOBAL_LANE,
    interval_env: str = "GEMINI_REQUEST_INTERVAL_MS",
    default_ms: int = 0,
) -> None:
    """비동기 경로용 스로틀 — 지정 레인 슬롯 예약 후 필요한 만큼 비동기 대기한다.

    인자 없이 호출하면 전역 레인 + GEMINI_REQUEST_INTERVAL_MS(기존 동작, default 0).
    ExamForge 등은 lane/interval_env/default_ms 를 명시해 전용 레인을 탄다.
    """
    delay = _reserve_slot(lane, interval_env, default_ms)
    if delay > 0.0:
        await asyncio.sleep(delay)


def wait_for_slot_sync(
    *,
    lane: str = _GLOBAL_LANE,
    interval_env: str = "GEMINI_REQUEST_INTERVAL_MS",
    default_ms: int = 0,
) -> None:
    """동기 경로용 스로틀 — 별도 스레드 등 이벤트 루프 밖에서 사용한다."""
    delay = _reserve_slot(lane, interval_env, default_ms)
    if delay > 0.0:
        time.sleep(delay)


def reset_throttle() -> None:
    """모든 레인의 스로틀 상태 초기화 — 테스트 격리용."""
    with _registry_lock:
        for key in _lane_next_allowed_at:
            _lane_next_allowed_at[key] = 0.0


def retry_attempts() -> int:
    """모델당 재시도 포함 총 시도 횟수(기본 5, 1~10 범위로 보정)."""
    value = _env_int("GEMINI_TEXT_RETRY_ATTEMPTS", _DEFAULT_RETRY_ATTEMPTS)
    return max(1, min(10, value))


def backoff_delay_sec(attempt: int) -> float:
    """attempt(0부터) 번째 실패 후 대기 시간(초) — 초기값 ×2^attempt, 상한 캡."""
    initial_ms = max(0, _env_int("GEMINI_TEXT_RETRY_INITIAL_MS", _DEFAULT_RETRY_INITIAL_MS))
    max_ms = max(0, _env_int("GEMINI_TEXT_RETRY_MAX_MS", _DEFAULT_RETRY_MAX_MS))
    delay_ms = min(initial_ms * (2 ** max(0, attempt)), max_ms)
    return delay_ms / 1000.0


def request_timeout_sec() -> float | None:
    """단일 SDK 호출 타임아웃(초). 0 이하이면 None(타임아웃 비활성)."""
    timeout_ms = _env_int("GEMINI_TEXT_TIMEOUT_MS", _DEFAULT_TIMEOUT_MS)
    return timeout_ms / 1000.0 if timeout_ms > 0 else None


def model_chain(primary: str) -> list[str]:
    """현재 모델을 선두로 한 Gemini 내부 폴백 모델 순서를 반환한다.

    GEMINI_TEXT_MODEL_FALLBACKS 의 순서를 보존하되 현재 모델과 중복되는
    항목은 제거한다. 목록이 비면 현재 모델 단독 체인이 된다.
    """
    raw = os.getenv("GEMINI_TEXT_MODEL_FALLBACKS", _DEFAULT_MODEL_FALLBACKS)
    fallbacks = [item.strip() for item in raw.split(",") if item.strip()]
    return [primary] + [model for model in fallbacks if model != primary]
