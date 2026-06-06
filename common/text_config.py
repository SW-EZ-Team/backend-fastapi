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
    return os.getenv("CLAUDE_SONNET_MODEL", "claude-sonnet-4-6")


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


def google_api_key() -> str | None:
    """Google AI Studio API 키를 반환한다. GEMINI_API_KEY를 대체 키로 허용한다."""
    value = os.getenv("GOOGLE_API_KEY", "").strip()
    if value:
        return value
    fallback = os.getenv("GEMINI_API_KEY", "").strip()
    return fallback if fallback else None


def gemini_text_model() -> str:
    """google-genai 텍스트 커넥터가 사용할 Gemini 모델 ID를 반환한다."""
    return os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash"


# Gemini 3 계열(gemini-3.5-flash 등)은 thinking_budget를 지원하지 않고 thinking_level만
# 받는다(공식 문서). 채팅 답변에 reasoning 스크래치패드가 새지 않게 기본을 LOW로 둔다.
_GEMINI_THINKING_LEVELS: frozenset[str] = frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"})


def gemini_thinking_level() -> str:
    """Gemini 텍스트 생성의 thinking_level을 반환한다(기본 LOW).

    reasoning 모델이 추론 텍스트를 답변 본문에 노출하는 것을 막기 위해 사고량을
    최소화한다. 허용값: MINIMAL / LOW / MEDIUM / HIGH. 잘못된 값은 LOW로 폴백한다.
    """
    raw = os.getenv("GEMINI_THINKING_LEVEL", "LOW").strip().upper()
    return raw if raw in _GEMINI_THINKING_LEVELS else "LOW"


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


