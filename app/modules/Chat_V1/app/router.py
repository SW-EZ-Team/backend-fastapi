"""Chat_V1 FastAPI 라우터.

POST /api/chat/v1/ask   — 텍스트 채팅 (Claude Sonnet)
POST /api/chat/v1/voice — 음성 채팅 (Gemini Flash Live)
POST /api/chat/v1/health
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.modules.Chat_V1.app.schemas import (
    ChatRequest,
    ChatResponse,
    VoiceChatRequest,
    VoiceChatResponse,
)
from app.modules.Chat_V1.app.service import answer_question
from app.modules.Chat_V1.app.voice_service import answer_voice_question

router = APIRouter(prefix="/api/chat/v1", tags=["chat-v1"])


@router.post("/ask", response_model=ChatResponse)
async def ask(request: ChatRequest) -> ChatResponse:
    """학생 질문에 강의 컨텍스트를 바탕으로 텍스트 답변한다.

    요청에 포함된 lecture_context(슬라이드·대본·퀴즈)를 참조해
    Claude Sonnet이 답변을 생성하고 참조 슬라이드 목록을 반환한다.
    """
    try:
        return await answer_question(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/voice", response_model=VoiceChatResponse)
async def voice_chat(request: VoiceChatRequest) -> VoiceChatResponse:
    """음성으로 학습 질문 — Gemini Flash Live.

    base64 인코딩된 음성 데이터를 받아 Gemini Flash Live 가 ASR + 생성 + TTS 를
    단일 호출로 처리한다. 음성 응답(WAV base64)과 트랜스크립트를 함께 반환한다.
    """
    try:
        return await answer_voice_question(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/health")
async def health() -> dict[str, str]:
    """Chat_V1 라우터 헬스체크."""
    return {"status": "ok", "service": "chat-v1"}
