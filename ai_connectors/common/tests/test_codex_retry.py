"""공용 codex_retry 모듈 단위 테스트.

3개 codex 커넥터가 공유하는 retry 정책의 핵심 동작을 단일 소스에서 검증한다:
    - transient 판정(503/429/5xx/연결/과부하) + 영구오류 구분
    - 지수 백오프 증가
    - run_codex_with_retry: transient→재시도→성공, 영구→즉시실패, 한도초과→예외
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ai_connectors.common.codex_retry import (
    CodexRetryPolicy,
    backoff_delay,
    is_transient_error,
    run_codex_with_retry,
)


# ── is_transient_error: transient 키워드 ─────────────────────────────────

@pytest.mark.parametrize(
    "text",
    [
        "error: 503 service unavailable",
        "websocket connection dropped",
        "econnrefused 127.0.0.1",
        "request timeout after 30s",
        "temporarily unavailable, retry later",
    ],
)
def test_transient_connection_keywords(text: str) -> None:
    """연결·5xx 계열 키워드는 transient로 판별한다."""
    assert is_transient_error(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "http 429 too many requests",
        "rate limit exceeded for this account",
        "the model is overloaded right now",
        "500 internal server error",
        "502 bad gateway",
        "504 gateway timeout",
    ],
)
def test_transient_rate_limit_and_5xx_keywords(text: str) -> None:
    """P1 보강: 429/rate limit/과부하/500/502/504도 transient로 판별한다."""
    assert is_transient_error(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "authentication failed: invalid oauth token",
        "schema validation error: missing field 'text'",
        "unknown argument --frobnicate",
        "permission denied",
    ],
)
def test_permanent_errors_not_transient(text: str) -> None:
    """인증·인자·스키마 위반은 영구 오류이므로 transient가 아니다."""
    assert is_transient_error(text) is False


# ── P2 회귀: bare 숫자 substring 오판 방지(단어 경계 매칭) ────────────────

@pytest.mark.parametrize(
    "text",
    [
        "error code 4295",      # 4295에 묻힌 429 — transient 아님
        "request id 5002",      # 5002에 묻힌 500 — transient 아님
        "error 50029 unknown",  # 50029에 묻힌 500 — transient 아님
        "error 4290",           # 4290에 묻힌 429 — transient 아님
        "build artifact 5040",  # 5040에 묻힌 504 — transient 아님
    ],
)
def test_numeric_substring_not_transient(text: str) -> None:
    """P2 회귀: 더 긴 숫자에 묻힌 HTTP 코드는 transient로 오판하지 않는다."""
    assert is_transient_error(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "http 429 too many requests",   # 단어 경계 429 + 텍스트 키워드
        "503 service unavailable",       # 단어 경계 503 + 텍스트 키워드
        "status: 502",                   # 단어 경계 502
        " 504 ",                         # 공백 경계 504
        "received 500 from upstream",    # 단어 경계 500
    ],
)
def test_bounded_status_code_is_transient(text: str) -> None:
    """P2 회귀: 단어 경계로 분리된 HTTP 코드는 transient로 재시도한다."""
    assert is_transient_error(text) is True


# ── backoff_delay: 지수 증가 ─────────────────────────────────────────────

def test_backoff_delay_exponential_growth() -> None:
    """attempt가 커질수록 기저 대기 시간이 지수적으로 커진다."""
    policy = CodexRetryPolicy()  # base 0.5, jitter 0.3
    d0 = backoff_delay(0, policy)
    d1 = backoff_delay(1, policy)
    d2 = backoff_delay(2, policy)
    assert 0.5 <= d0 <= 0.8
    assert 1.0 <= d1 <= 1.3
    assert 2.0 <= d2 <= 2.3


# ── run_codex_with_retry: 재시도 루프 ────────────────────────────────────

def _perm(out: str, err: str) -> Exception:
    return RuntimeError(f"영구실패: {err or out}")


def _exh(out: str, err: str, rc: int) -> Exception:
    return RuntimeError(f"한도초과(rc={rc}): {err or out}")


@pytest.mark.asyncio
async def test_run_transient_then_success() -> None:
    """transient 1회 후 성공 → 재시도해 (stdout, stderr)를 반환한다."""
    results = iter([("", "503 service unavailable", 1), ("정상 stdout", "", 0)])

    async def run_once() -> tuple[str, str, int]:
        return next(results)

    with patch("ai_connectors.common.codex_retry.asyncio.sleep", new=AsyncMock()):
        stdout, stderr = await run_codex_with_retry(
            run_once, on_permanent=_perm, on_exhausted=_exh
        )
    assert stdout == "정상 stdout"


@pytest.mark.asyncio
async def test_run_permanent_error_no_retry() -> None:
    """영구 오류는 재시도하지 않고 즉시 on_permanent 예외를 던진다."""
    call_count = 0

    async def run_once() -> tuple[str, str, int]:
        nonlocal call_count
        call_count += 1
        return ("", "authentication failed", 1)

    with pytest.raises(RuntimeError, match="영구실패"):
        await run_codex_with_retry(run_once, on_permanent=_perm, on_exhausted=_exh)
    assert call_count == 1


@pytest.mark.asyncio
async def test_run_exhaustion_raises() -> None:
    """transient가 한도까지 계속되면 on_exhausted 예외를 던진다."""
    call_count = 0

    async def run_once() -> tuple[str, str, int]:
        nonlocal call_count
        call_count += 1
        return ("", "429 too many requests", 1)

    policy = CodexRetryPolicy(max_retries=2)
    with patch("ai_connectors.common.codex_retry.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="한도초과"):
            await run_codex_with_retry(
                run_once, on_permanent=_perm, on_exhausted=_exh, policy=policy
            )
    # 최초 1회 + 재시도 2회 = 총 3회 호출
    assert call_count == 3
