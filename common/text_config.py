"""텍스트 생성 커넥터 공용 설정.

Claude Sonnet / Codex CLI 관련 환경변수를 한 곳에서만 읽는다.
다른 모듈은 os.getenv() 직접 호출 대신 여기 함수를 참조한다.
"""
from __future__ import annotations

import os


def anthropic_api_key() -> str | None:
    """Anthropic API 키를 반환한다. 없으면 None."""
    return os.getenv("ANTHROPIC_API_KEY") or None


def claude_sonnet_api_key() -> str | None:
    """Claude Sonnet 커넥터 API 키를 반환한다.

    CLAUDE_SONNET_API_KEY 가 우선. 없으면 ANTHROPIC_API_KEY 를 공유한다.
    """
    specific = os.getenv("CLAUDE_SONNET_API_KEY", "").strip()
    return specific if specific else anthropic_api_key()


def claude_sonnet_model() -> str:
    """사용할 Claude Sonnet 모델 식별자를 반환한다."""
    return os.getenv("CLAUDE_SONNET_MODEL", "claude-sonnet-4-5-20250929")


def claude_sonnet_timeout_sec() -> float:
    """Claude Sonnet 단일 호출 제한 시간(초)를 반환한다."""
    raw = os.getenv("CLAUDE_SONNET_TIMEOUT_SEC", "300").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("CLAUDE_SONNET_TIMEOUT_SEC는 숫자여야 한다.") from exc
    if value < 30 or value > 1200:
        raise RuntimeError("CLAUDE_SONNET_TIMEOUT_SEC는 30~1200초여야 한다.")
    return value


def claude_sonnet_max_concurrency() -> int:
    """Claude Sonnet 배치 호출 병렬 상한을 반환한다."""
    raw = os.getenv("CLAUDE_SONNET_MAX_CONCURRENCY", "4").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("CLAUDE_SONNET_MAX_CONCURRENCY는 정수여야 한다.") from exc
    if value < 1 or value > 8:
        raise RuntimeError("CLAUDE_SONNET_MAX_CONCURRENCY는 1~8이어야 한다.")
    return value


def codex_cli_model() -> str:
    """Codex CLI 모델 이름을 반환한다."""
    return os.getenv("CODEX_CLI_MODEL", "gpt-5.4")


def codex_cli_reasoning_effort() -> str:
    """Codex CLI 추론 강도를 반환한다. low/medium/high/xhigh 중 하나."""
    value = (os.getenv("CODEX_CLI_REASONING_EFFORT") or "low").strip()
    if value not in {"low", "medium", "high", "xhigh"}:
        raise RuntimeError("CODEX_CLI_REASONING_EFFORT 값이 올바르지 않다.")
    return value


def codex_cli_timeout_sec() -> int:
    """Codex CLI 단일 실행 제한 시간(초)를 반환한다."""
    raw = os.getenv("CODEX_CLI_TIMEOUT_SEC", "180").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("CODEX_CLI_TIMEOUT_SEC는 정수여야 한다.") from exc
    if value < 30 or value > 600:
        raise RuntimeError("CODEX_CLI_TIMEOUT_SEC는 30~600초여야 한다.")
    return value
