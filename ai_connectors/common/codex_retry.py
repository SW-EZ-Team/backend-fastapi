"""codex CLI 서브프로세스 호출의 transient 재시도 공용 헬퍼.

3개 codex 커넥터(ai_connectors/text, ChapterStudio_V1/ai_connectors,
ExamProge_V1/common/_connector_codex)가 모두 이 모듈을 import 해 동일한
재시도 정책을 쓴다. 중복 정의를 제거해 한 곳만 고치고 다른 곳을 놓치는
드리프트를 차단한다.

핵심 정책:
    - transient 오류(503/429/연결/과부하 등 일시적 장애)는 지수 백오프 재시도.
    - 영구 오류(인증 실패·잘못된 인자·스키마 위반)는 재시도하지 않고 즉시 실패.
    - 동시호출 세마포어로 과한 병렬이 503을 유발하지 않게 한다.
    - 빈 except로 오류를 삼키지 않는다(워크어라운드 아님 — 정당한 retry 패턴).
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# transient(일시적) 오류 판정 텍스트 키워드 — 결합 출력(stdout+stderr) 소문자에
# substring으로 포함되면 재시도. 충분히 길고 고유한 문구만 둔다(오판 위험 낮음).
# codex/ChatGPT OAuth 과부하 시 가장 흔한 rate limit·5xx 게이트웨이 문구를 포함한다.
_TRANSIENT_TEXT_KEYWORDS: tuple[str, ...] = (
    # WebSocket·연결 계열
    "service unavailable",
    "websocket",
    "connection",
    "network",
    "connect error",
    "econnrefused",
    "econnreset",
    "timeout",
    "temporarily unavailable",
    # rate limit·과부하 계열(P1 보강)
    "too many requests",
    "rate limit",
    "overloaded",
    # 기타 게이트웨이 5xx 문구(P1 보강)
    "internal server error",
    "bad gateway",
    "gateway timeout",
)

# bare 숫자 HTTP 상태 코드 — substring이면 "error code 4295" 같은 무관 숫자를
# 오판하므로 단어 경계(\b)로만 매칭한다. " 429 ", "http 429", "status: 503" 등은
# 잡고 "4295"·"5002"처럼 더 긴 숫자에 묻힌 경우는 잡지 않는다(P2 오판 차단).
_TRANSIENT_STATUS_CODE_RE = re.compile(r"\b(429|500|502|503|504)\b")


@dataclass(frozen=True)
class CodexRetryPolicy:
    """codex 재시도 정책 — 횟수·백오프·동시성을 한 곳에서 결정한다."""

    max_retries: int = 3        # 최초 시도 외 추가 재시도 횟수(총 4회 시도)
    base_delay_sec: float = 0.5  # 최초 대기 시간(초) — 0.5→1→2→4 지수 증가
    max_jitter_sec: float = 0.3  # 지터 최대값(초) — thundering herd 완화
    max_concurrent: int = 3      # 동시 호출 상한 — 과한 병렬이 503 유발 방지


DEFAULT_RETRY_POLICY = CodexRetryPolicy()

# 동시호출 세마포어 — 이벤트 루프당 1개를 지연 생성한다.
_semaphore: asyncio.Semaphore | None = None


def get_codex_semaphore(policy: CodexRetryPolicy = DEFAULT_RETRY_POLICY) -> asyncio.Semaphore:
    """codex 동시호출 제한 세마포어를 지연 생성해 반환한다.

    프로세스 전역 단일 세마포어로 3개 커넥터가 함께 동시성을 공유한다.
    """
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(policy.max_concurrent)
    return _semaphore


def is_transient_error(combined_lower: str) -> bool:
    """표준 출력·표준 에러 결합 문자열로 transient 오류 여부를 판별한다.

    판정은 두 갈래로 한다:
    - 텍스트 키워드(service unavailable/too many requests 등)는 substring 매칭.
    - bare 숫자 HTTP 코드(429/5xx)는 단어 경계 정규식 매칭 — "error code 4295"
      처럼 더 긴 숫자에 묻힌 경우를 transient로 오판하지 않게 한다.

    인증 실패·잘못된 인자 등 영구 오류는 False를 반환한다.

    Args:
        combined_lower: (stdout + stderr).lower() 결합 문자열.
    """
    if any(kw in combined_lower for kw in _TRANSIENT_TEXT_KEYWORDS):
        return True
    return _TRANSIENT_STATUS_CODE_RE.search(combined_lower) is not None


def backoff_delay(attempt: int, policy: CodexRetryPolicy = DEFAULT_RETRY_POLICY) -> float:
    """지수 백오프 + 지터 대기 시간을 계산한다.

    attempt=0 → ~base, attempt=1 → ~base*2, attempt=2 → ~base*4 에 지터를 더한다.
    """
    base = policy.base_delay_sec * (2 ** attempt)
    jitter = random.uniform(0.0, policy.max_jitter_sec)
    return base + jitter


async def run_codex_with_retry(
    run_once: Callable[[], Awaitable[tuple[str, str, int]]],
    *,
    on_permanent: Callable[[str, str], Exception],
    on_exhausted: Callable[[str, str, int], Exception],
    policy: CodexRetryPolicy = DEFAULT_RETRY_POLICY,
    connector_label: str = "codex_cli",
) -> tuple[str, str]:
    """codex 서브프로세스 호출을 transient 재시도와 함께 실행한다.

    각 커넥터는 커맨드 구성·응답 파싱을 그대로 유지하고, 이 헬퍼에 서브프로세스
    실행 클로저(run_once)만 위임한다. 성공 시 (stdout, stderr)를 반환하며,
    영구 오류·재시도 한도 초과 시 호출자가 준 예외 팩토리로 예외를 만든다.

    Args:
        run_once: 매 시도마다 서브프로세스를 1회 실행해 (stdout, stderr, returncode)를
            반환하는 코루틴 팩토리. 세마포어 획득은 이 함수가 담당한다.
        on_permanent: 영구 오류(transient 아님) 시 (stdout, stderr)로 예외를 만드는 팩토리.
        on_exhausted: 재시도 한도 초과 시 (stdout, stderr, returncode)로 예외를 만드는 팩토리.
        policy: 재시도 정책.
        connector_label: 로그 식별용 라벨.

    Returns:
        성공한 호출의 (stdout, stderr).

    Raises:
        on_permanent(...) 또는 on_exhausted(...)가 만든 예외.
    """
    semaphore = get_codex_semaphore(policy)
    last_stdout = ""
    last_stderr = ""
    last_returncode = 0
    for attempt in range(policy.max_retries + 1):
        async with semaphore:
            stdout, stderr, returncode = await run_once()
        if returncode == 0:
            return stdout, stderr
        last_stdout, last_stderr, last_returncode = stdout, stderr, returncode
        combined = (stdout + stderr).lower()
        if not is_transient_error(combined):
            # 영구 오류는 재시도하지 않고 즉시 실패한다.
            raise on_permanent(stdout, stderr)
        if attempt < policy.max_retries:
            delay = backoff_delay(attempt, policy)
            logger.warning(
                "%s transient 오류(rc=%d) — %d/%d 회 재시도, %.2f초 대기: %s",
                connector_label,
                returncode,
                attempt + 1,
                policy.max_retries,
                delay,
                (stdout + stderr).strip()[-200:],
            )
            await asyncio.sleep(delay)
    # 재시도 한도 초과 — 명확한 예외로 올린다.
    raise on_exhausted(last_stdout, last_stderr, last_returncode)
