"""Chat_V1 음성 서비스 — Gemini Flash Live 커넥터 호출.

강의 컨텍스트를 시스템 프롬프트에 주입하고 음성 질문에 답변한다.
텍스트 서비스의 build_system_prompt/extract_referenced_slides 를 재사용한다.
"""
from __future__ import annotations

from ai_connectors.voice.gemini_flash_live.connector import GeminiFlashLiveConnector
from ai_connectors.voice.gemini_flash_live.schemas import VoiceRequest

from app.modules.Chat_V1.app.schemas import VoiceChatRequest, VoiceChatResponse
from app.modules.Chat_V1.pipeline.voice_graph import run_voice_pipeline


async def answer_voice_question(request: VoiceChatRequest) -> VoiceChatResponse:
    """음성 채팅 요청을 음성 파이프라인에 통과시켜 구조화된 응답을 반환한다.

    파이프라인이 validate_voice → generate_voice_answer → format_voice_response
    순으로 실행되며, 최종 상태에서 VoiceChatResponse 를 조립한다.
    """
    final_state = await run_voice_pipeline(request)
    return VoiceChatResponse(
        session_id=request.session_id,
        audio_data=final_state["audio_output"],
        audio_format=final_state.get("audio_format_out", "wav"),
        transcript_input=final_state.get("transcript_input", ""),
        transcript_output=final_state.get("transcript_output", ""),
        referenced_slides=final_state.get("referenced_slides", []),
    )


async def call_gemini_flash_live(
    audio_data: str,
    audio_format: str,
    sample_rate: int,
    system_prompt: str,
) -> tuple[str, str, str]:
    """Gemini Flash Live 커넥터를 호출해 (audio_b64, transcript_in, transcript_out) 를 반환한다.

    반환 형태를 튜플로 고정해 호출 노드가 상태를 직접 분해하도록 한다.
    """
    connector = GeminiFlashLiveConnector()
    req = VoiceRequest(
        audio_data=audio_data,
        audio_format=audio_format,
        sample_rate=sample_rate,
        system_prompt=system_prompt,
    )
    response = await connector.voice_chat(req)
    return response.audio_data, response.transcript_input, response.transcript_output
