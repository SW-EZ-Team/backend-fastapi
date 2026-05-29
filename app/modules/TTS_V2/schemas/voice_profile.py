"""음성 프로필 CRUD API 용 Pydantic 스키마다."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CreateVoiceProfileRequest(BaseModel):
    """사용자 음성 프로필 등록 요청 모델.

    ref_audio_base64 는 base64 인코딩된 오디오 바이너리다.
    언어 코드는 ISO 639-1 두 자리 코드를 사용한다 (예: ko, en, ja).
    """

    user_id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    # base64 인코딩된 오디오 바이너리 — 서버에서 24000Hz mono WAV 로 정규화 저장
    ref_audio_base64: str
    ref_text: str = Field(..., min_length=1, max_length=500)
    language: str = Field(default="ko", max_length=10)


class VoiceProfileSummary(BaseModel):
    """프로필 목록·단건 조회 응답 모델.

    source 필드는 'user' 또는 'tutor' 로 구분된다.
    """

    profile_id: str
    name: str
    language: str
    sample_rate: int
    duration_sec: float
    # 'user' = 사용자 업로드, 'tutor' = 고정 튜터 프로필
    source: str = "user"


class VoiceProfileListResponse(BaseModel):
    """음성 프로필 목록 응답 모델."""

    profiles: list[VoiceProfileSummary]


class DeleteVoiceProfileResponse(BaseModel):
    """음성 프로필 삭제 응답 모델."""

    deleted: bool
    profile_id: str
