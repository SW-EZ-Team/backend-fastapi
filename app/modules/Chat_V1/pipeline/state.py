"""Chat_V1 LangGraph 파이프라인 상태 정의.

텍스트 채팅(Claude Sonnet) 과 음성 채팅(Gemini Flash Live) 두 파이프라인을 지원한다.
mode 필드로 어느 경로를 타는지 구분한다.
"""
from __future__ import annotations

from typing import TypedDict


class ChatState(TypedDict, total=False):
    """텍스트 챗봇 파이프라인 전체 상태.

    validate_input → generate_answer → format_response 노드 순서로 흐른다.
    """

    # 입력 (validate_input 노드가 채운다)
    session_id: str
    user_message: str
    system_prompt: str

    # 중간 결과 (generate_answer 노드가 채운다)
    raw_answer: str

    # 최종 출력 (format_response 노드가 채운다)
    answer: str
    referenced_slides: list[int]

    # 오류 상태
    error_message: str | None
    pipeline_status: str


class VoiceChatState(TypedDict, total=False):
    """음성 챗봇 파이프라인 전체 상태.

    validate_voice → generate_voice_answer → format_voice_response 노드 순서로 흐른다.
    Gemini Flash Live 가 ASR + 생성 + TTS 를 단일 호출로 처리한다.
    """

    # 입력 (validate_voice 노드가 채운다)
    session_id: str
    audio_input: str        # base64 인코딩된 입력 오디오
    audio_format: str       # 입력 오디오 포맷 (webm, wav, pcm)
    sample_rate: int        # 입력 오디오 샘플레이트
    system_prompt: str      # 강의 컨텍스트 시스템 프롬프트

    # 중간 결과 (generate_voice_answer 노드가 채운다)
    raw_audio_output: str   # base64 인코딩된 원시 음성 응답
    transcript_input: str   # 사용자 음성 → 텍스트
    transcript_output: str  # AI 응답 텍스트

    # 최종 출력 (format_voice_response 노드가 채운다)
    audio_output: str       # base64 인코딩된 최종 WAV 음성 응답
    audio_format_out: str   # 출력 오디오 포맷
    referenced_slides: list[int]

    # 오류 상태
    error_message: str | None
    pipeline_status: str
