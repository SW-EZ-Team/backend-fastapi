"""Gemini Flash Live 음성 커넥터 환경변수 설정.

GEMINI_API_KEY 또는 GOOGLE_API_KEY 로 인증한다.
모델 식별자와 오디오 설정을 한 곳에서만 읽는다.
"""
from __future__ import annotations

import os


def gemini_api_key() -> str | None:
    """Gemini API 키를 반환한다.

    GEMINI_API_KEY 가 우선, 없으면 GOOGLE_API_KEY 를 공유한다.
    """
    specific = os.getenv("GEMINI_API_KEY", "").strip()
    if specific:
        return specific
    fallback = os.getenv("GOOGLE_API_KEY", "").strip()
    return fallback if fallback else None


def gemini_flash_live_model() -> str:
    """사용할 Gemini Flash Live 모델 식별자를 반환한다."""
    return os.getenv("GEMINI_FLASH_LIVE_MODEL", "gemini-2.0-flash-live-001")


def gemini_flash_live_timeout_sec() -> float:
    """Gemini Flash Live 단일 호출 제한 시간(초)를 반환한다."""
    raw = os.getenv("GEMINI_FLASH_LIVE_TIMEOUT_SEC", "60").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("GEMINI_FLASH_LIVE_TIMEOUT_SEC는 숫자여야 한다.") from exc
    if value < 10 or value > 300:
        raise RuntimeError("GEMINI_FLASH_LIVE_TIMEOUT_SEC는 10~300초여야 한다.")
    return value
