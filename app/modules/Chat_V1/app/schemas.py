"""Chat_V1 요청/응답 스키마 (Pydantic v2).

스프링이 전달하는 채팅 요청과 챗봇이 반환하는 응답을 정의한다.
LectureContext는 ChapterStudio 산출물(슬라이드·음성대본·퀴즈)을 담는다.

텍스트 채팅(Claude Sonnet)과 음성 채팅(Gemini Flash Live) 두 모드를 지원한다.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SlideContext(BaseModel):
    """단일 슬라이드의 제목과 핵심 내용."""

    model_config = ConfigDict(strict=True, frozen=True)

    slide_idx: int = Field(ge=0, description="슬라이드 인덱스 (0-based)")
    title: str = Field(min_length=1, description="슬라이드 제목")
    content: str = Field(min_length=1, description="슬라이드 핵심 내용")


class LectureContext(BaseModel):
    """강의 콘텐츠 컨텍스트 — ChapterStudio 산출물 기반.

    slides는 필수이며, voice_scripts와 quiz_items는 선택 제공된다.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    chapter_title: str = Field(min_length=1, description="챕터 제목")
    slides: list[SlideContext] = Field(min_length=1, description="슬라이드 목록")
    voice_scripts: list[str] | None = Field(
        default=None, description="음성대본 텍스트 (선택)"
    )
    quiz_items: list[str] | None = Field(
        default=None, description="퀴즈 항목 (선택)"
    )


class ChatRequest(BaseModel):
    """스프링에서 전달받는 채팅 요청.

    슬라이드 컨텍스트 필드(lesson_id/slide_id/slide_idx)는 선택값이다.
    Spring ChatService.buildFastapiRequestBody가 snake_case로 전송하므로
    snake_case 그대로 수신한다. 모두 없으면 슬라이드 컨텍스트 없이 폴백한다.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    session_id: str = Field(min_length=1, description="채팅 세션 식별자")
    user_message: str = Field(min_length=1, description="학생 질문")
    lecture_context: LectureContext = Field(description="강의 콘텐츠 컨텍스트")
    # Spring이 보내는 현재 슬라이드 위치 식별자 — spring_adapter가 DB 조회에 사용
    lesson_id: str | None = Field(default=None, description="챕터(강의) ID — public.slide.chapter_id에 대응")
    slide_id: str | None = Field(default=None, description="슬라이드 ID — public.slide.id에 대응")
    slide_idx: int | None = Field(default=None, ge=0, description="슬라이드 인덱스 (0-based)")


class ChatResponse(BaseModel):
    """챗봇 응답."""

    model_config = ConfigDict(strict=True, frozen=True)

    session_id: str = Field(description="채팅 세션 식별자")
    answer: str = Field(description="챗봇 답변")
    referenced_slides: list[int] = Field(
        default_factory=list, description="참조한 슬라이드 인덱스 목록"
    )


class ChatMode(str, Enum):
    """채팅 모드 — 텍스트(Claude Sonnet) 또는 음성(Gemini Flash Live)."""

    TEXT = "text"
    VOICE = "voice"


class VoiceChatRequest(BaseModel):
    """스프링에서 전달받는 음성 채팅 요청.

    audio_data: 브라우저 MediaRecorder 가 생성한 base64 인코딩 오디오
    lecture_context: 텍스트 채팅과 동일한 강의 컨텍스트
    """

    model_config = ConfigDict(strict=True, frozen=True)

    session_id: str = Field(min_length=1, description="채팅 세션 식별자")
    audio_data: str = Field(min_length=1, description="base64 인코딩된 음성 데이터")
    audio_format: str = Field(default="webm", description="오디오 포맷 (webm, wav, pcm)")
    sample_rate: int = Field(
        default=16000,
        ge=8000,
        le=48000,
        description="입력 오디오 샘플레이트 (Hz)",
    )
    lecture_context: LectureContext = Field(description="강의 콘텐츠 컨텍스트")


class VoiceChatResponse(BaseModel):
    """음성 챗봇 응답.

    audio_data: base64 인코딩된 WAV 음성 응답
    transcript_input: 사용자가 말한 내용의 텍스트 변환
    transcript_output: AI 가 생성한 답변 텍스트 (슬라이드 참조 파싱 원본)
    """

    model_config = ConfigDict(strict=True, frozen=True)

    session_id: str = Field(description="채팅 세션 식별자")
    audio_data: str = Field(description="base64 인코딩된 WAV 음성 응답")
    audio_format: str = Field(default="wav", description="출력 오디오 포맷")
    transcript_input: str = Field(description="사용자 음성 → 텍스트 변환 결과")
    transcript_output: str = Field(description="AI 응답 텍스트")
    referenced_slides: list[int] = Field(
        default_factory=list, description="참조한 슬라이드 인덱스 목록 (0-based)"
    )
