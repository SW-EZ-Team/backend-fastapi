"""Chat_V1 학습 챗봇 모듈의 공개 진입점.

텍스트 채팅(Claude Sonnet)과 음성 채팅(Gemini Flash Live) 두 모드를 지원한다.
"""

from app.modules.Chat_V1.app.router import router
from app.modules.Chat_V1.app.schemas import (
    ChatRequest,
    ChatResponse,
    ChatMode,
    VoiceChatRequest,
    VoiceChatResponse,
)
from app.modules.Chat_V1.app.service import answer_question
from app.modules.Chat_V1.app.voice_service import answer_voice_question

__all__ = [
    "router",
    "ChatRequest",
    "ChatResponse",
    "ChatMode",
    "VoiceChatRequest",
    "VoiceChatResponse",
    "answer_question",
    "answer_voice_question",
]
