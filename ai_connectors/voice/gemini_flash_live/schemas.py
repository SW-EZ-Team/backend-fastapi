"""Gemini Flash Live 음성 커넥터 전용 요청/응답 스키마 (Pydantic v2).

오디오 데이터는 base64 인코딩 문자열로 전달된다.
커넥터 내부에서 bytes 로 변환 후 Gemini API 에 전달한다.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VoiceRequest(BaseModel):
    """음성 채팅 커넥터 요청.

    audio_data: base64 로 인코딩된 음성 입력 바이트
    system_prompt: 강의 컨텍스트를 포함한 시스템 프롬프트
    """

    model_config = ConfigDict(strict=True, frozen=True)

    audio_data: str = Field(min_length=1, description="base64 인코딩된 음성 바이트")
    audio_format: str = Field(
        default="webm",
        description="입력 오디오 포맷 (webm, wav, pcm)",
    )
    sample_rate: int = Field(
        default=16000,
        ge=8000,
        le=48000,
        description="입력 오디오 샘플레이트 (Hz)",
    )
    system_prompt: str = Field(
        default="",
        description="강의 컨텍스트 시스템 프롬프트",
    )


class VoiceResponse(BaseModel):
    """음성 채팅 커넥터 응답.

    audio_data: base64 로 인코딩된 음성 응답 바이트
    transcript_input: 사용자 음성을 텍스트로 변환한 결과
    transcript_output: AI 가 생성한 텍스트 답변
    """

    model_config = ConfigDict(strict=True, frozen=True)

    audio_data: str = Field(description="base64 인코딩된 음성 응답 바이트")
    audio_format: str = Field(default="wav", description="출력 오디오 포맷")
    transcript_input: str = Field(description="사용자 음성 → 텍스트 변환 결과")
    transcript_output: str = Field(description="AI 응답 텍스트")
    referenced_slides: list[int] = Field(
        default_factory=list,
        description="응답에서 참조된 슬라이드 인덱스 목록 (0-based)",
    )
