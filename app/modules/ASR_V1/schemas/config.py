"""런타임 세션 설정 스키마.

WebSocket 클라이언트가 전송하는 설정 오버라이드를 검증한다.
미지정 필드는 pipeline/config.py 기본값을 유지한다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SessionConfig(BaseModel):
    """WebSocket 세션 초기화 파라미터 (선택 전달)."""

    vad_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="VAD 음성 감지 임계값 (0.0~1.0)",
    )
    vad_min_silence_ms: int | None = Field(
        default=None,
        ge=100,
        description="침묵 판정 최소 시간(ms)",
    )
    turn_min_chars: int | None = Field(
        default=None,
        ge=1,
        description="턴 커밋 최소 글자수",
    )
    language: str = Field(
        default="ko",
        description="전사 언어 코드 (ISO 639-1)",
    )
    model: str | None = Field(
        default=None,
        description="ASR 커넥터 키 — 미지정 시 .env 기본값 사용",
    )
