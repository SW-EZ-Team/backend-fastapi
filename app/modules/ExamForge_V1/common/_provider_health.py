"""프로바이더 헬스 캐시 — 쿼터 소진 프로바이더의 경량 passive 기록.

목적
----
모든 활성 텍스트 프로바이더가 쿼터/사용한도 소진 상태일 때 비싼 모의고사 생성
파이프라인(~수십 LLM 호출)을 시작하면 전 호출이 400/429로 실패하며 시간·부분비용을
낭비한다. 이 모듈은 그런 "영구성" 소진을 **생성 도중 실제로 만난 오류로부터 수동(passive)
기록**해 두고, 다음 생성 시작 전 사전점검이 즉시 빠질 수 있게 한다.

핵심 원칙
---------
- **Passive only**: 라이브 프로빙 호출을 절대 하지 않는다. 커넥터가 실제 생성 중
  영구성 오류(Gemini 결제 429 / Anthropic 400 usage-limit / OpenAI 결제성 등)를 만났을
  때만 기록한다. 적극 프로브는 그 자체로 비용이라 금지한다.
- **메모리 캐시**: 프로세스 메모리에만 둔다(영속 불필요). 재시작하면 자연히 비워진다.
- **자동 해제**: until 시각이 지나면 자동으로 "살아있음"으로 되돌아간다(다시 시도 허용).
  벤더가 알려준 복구 날짜("regain access on 2026-07-01")가 있으면 그 시각까지,
  없으면 짧은 보수적 TTL(기본 10분)까지만 차단한다.
- **거짓 차단 금지**: 기록된(그리고 아직 until 이전인) 프로바이더만 소진으로 본다.
  하나라도 살아있으면 사전점검은 절대 막지 않는다.

스레드/이벤트루프 안전성
------------------------
단일 dict 에 대한 set/get 만 하며, 각 연산은 GIL 보호 하의 단일 원자적 dict 연산이다.
await 경계를 넘나드는 복합 read-modify-write 가 없으므로 별도 락 없이 안전하다.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
import time
from dataclasses import dataclass

_LOG = logging.getLogger(__name__)

# until 미지정 시 적용하는 보수적 기본 TTL(초). 짧게 둬 거짓 차단을 최소화한다 —
# 벤더가 복구 시각을 안 알려준 경우라도 10분 뒤에는 자동으로 재시도를 허용한다.
_DEFAULT_TTL_SEC = 600.0

# Anthropic 400 "usage limit ... regain access on 2026-07-01" 형태에서 복구일을 파싱.
# 날짜만 주어지므로 해당 일자의 00:00(UTC)을 복구 시각으로 본다(보수적: 그 날 자정부터 재시도).
_REGAIN_DATE_RE = re.compile(
    r"regain\s+access\s+on\s+(\d{4})-(\d{2})-(\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Entry:
    """소진 기록 1건 — 단조시계 기준 만료 시각과 사람이 읽을 사유."""

    # time.monotonic() 기준 만료 시각(초). 이 시각이 지나면 자동 해제된다.
    expires_monotonic: float
    reason: str


# 프로바이더 이름 → 소진 기록. 메모리 전용(영속 불필요).
_HEALTH: dict[str, _Entry] = {}


def _now() -> float:
    """현재 단조시계 값(초). 벽시계 점프(NTP 조정 등)에 영향받지 않는다."""
    return time.monotonic()


def parse_regain_until(message: str) -> float | None:
    """오류 메시지에서 '복구 시각'을 단조시계 기준 만료 초로 환산해 반환한다.

    Anthropic 의 "regain access on YYYY-MM-DD" 패턴을 인식한다. 미래 날짜면 지금부터
    그 시각까지의 차이를 단조시계에 더해 반환하고, 패턴이 없거나 이미 지난 날짜면
    None 을 반환한다(이 경우 호출부가 기본 TTL 로 폴백한다).
    """
    match = _REGAIN_DATE_RE.search(message or "")
    if match is None:
        return None
    year, month, day = (int(g) for g in match.groups())
    try:
        target = _dt.datetime(year, month, day, tzinfo=_dt.timezone.utc)
    except ValueError:
        return None
    now_wall = _dt.datetime.now(tz=_dt.timezone.utc)
    delta_sec = (target - now_wall).total_seconds()
    if delta_sec <= 0:
        # 이미 지난 복구일 — 차단하지 않는다(기본 TTL 폴백을 유도).
        return None
    return _now() + delta_sec


def mark_exhausted(
    provider: str,
    *,
    reason: str = "",
    until_monotonic: float | None = None,
    ttl_sec: float | None = None,
) -> None:
    """프로바이더를 '소진' 상태로 기록한다(passive — 실제 오류를 만났을 때만 호출).

    우선순위:
    1. until_monotonic 이 주어지면 그 시각까지 차단(벤더가 알려준 복구일 등).
    2. 아니면 ttl_sec(미지정 시 기본 _DEFAULT_TTL_SEC) 만큼 차단.

    같은 프로바이더가 이미 기록돼 있으면 만료가 더 늦은(더 보수적인) 쪽으로 갱신한다 —
    한 번이라도 더 긴 차단 신호를 받았으면 그걸 존중한다.
    """
    if not provider:
        return
    if until_monotonic is None:
        ttl = _DEFAULT_TTL_SEC if ttl_sec is None else max(0.0, ttl_sec)
        expires = _now() + ttl
    else:
        expires = until_monotonic

    existing = _HEALTH.get(provider)
    if existing is not None and existing.expires_monotonic >= expires:
        # 이미 더 늦은 만료가 기록돼 있으면 유지(축소 금지).
        return
    _HEALTH[provider] = _Entry(expires_monotonic=expires, reason=reason or "쿼터/사용한도 소진")
    _LOG.warning(
        "[ProviderHealth] '%s' 소진 기록 — %.0f초 차단 (사유: %s)",
        provider,
        max(0.0, expires - _now()),
        reason or "쿼터/사용한도 소진",
    )


def is_exhausted(provider: str) -> bool:
    """프로바이더가 현재 소진 상태인지 반환한다. until 이 지났으면 자동 해제한다."""
    entry = _HEALTH.get(provider)
    if entry is None:
        return False
    if entry.expires_monotonic <= _now():
        # 만료 — 자동 해제(다시 시도 허용).
        _HEALTH.pop(provider, None)
        return False
    return True


def all_exhausted(providers: list[str] | tuple[str, ...]) -> bool:
    """주어진 프로바이더 체인이 '비어있지 않고 전부' 소진 상태면 True.

    거짓 차단 방지의 핵심 함수다:
    - 체인이 비어 있으면(알 수 없는 활성 체인) 절대 막지 않는다 → False.
    - 하나라도 소진 기록이 없거나 until 이 지나 살아있으면 → False(정상 진행).
    - 모든 후보가 현재 소진 상태일 때만 → True(차단).
    """
    names = [p for p in providers if p]
    if not names:
        return False
    return all(is_exhausted(p) for p in names)


def reset() -> None:
    """전체 헬스 캐시를 비운다 — 테스트 격리 전용."""
    _HEALTH.clear()


def snapshot() -> dict[str, str]:
    """현재 살아있는(미만료) 소진 기록의 사유 맵을 반환한다 — 진단/로그용."""
    out: dict[str, str] = {}
    for provider in list(_HEALTH.keys()):
        if is_exhausted(provider):
            out[provider] = _HEALTH[provider].reason
    return out


__all__ = [
    "mark_exhausted",
    "is_exhausted",
    "all_exhausted",
    "parse_regain_until",
    "reset",
    "snapshot",
]
