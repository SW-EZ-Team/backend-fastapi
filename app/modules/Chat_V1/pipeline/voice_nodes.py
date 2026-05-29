"""Chat_V1 음성 파이프라인 LangGraph 노드 함수들.

Gemini Flash Live 를 통해 음성 입력 → 음성 응답을 처리한다.
각 노드는 순수하게 상태를 받아 업데이트된 상태를 반환한다.
"""
from __future__ import annotations

from ai_connectors.errors import AIConnectorError

from app.modules.Chat_V1.pipeline.state import VoiceChatState


def validate_voice(state: VoiceChatState) -> VoiceChatState:
    """음성 입력 유효성을 검증하고 시스템 프롬프트가 있는지 확인한다.

    audio_input 이나 system_prompt 가 비어 있으면 error_message 를 설정한다.
    """
    if not state.get("audio_input", "").strip():
        return {
            **state,
            "error_message": "음성 데이터가 비어 있어요.",
            "pipeline_status": "invalid_input",
        }
    if not state.get("system_prompt", "").strip():
        return {
            **state,
            "error_message": "강의 컨텍스트가 없어요.",
            "pipeline_status": "invalid_input",
        }
    return {**state, "pipeline_status": "validated"}


async def generate_voice_answer(state: VoiceChatState) -> VoiceChatState:
    """Gemini Flash Live 를 호출해 음성 응답과 트랜스크립트를 채운다.

    오류 발생 시 error_message 에 기록하고 파이프라인 상태를 failed 로 설정한다.
    """
    if state.get("error_message"):
        # 이전 노드에서 오류가 났으면 그대로 통과
        return state

    from app.modules.Chat_V1.app.voice_service import call_gemini_flash_live

    try:
        audio_b64, transcript_in, transcript_out = await call_gemini_flash_live(
            audio_data=state["audio_input"],
            audio_format=state.get("audio_format", "webm"),
            sample_rate=state.get("sample_rate", 16000),
            system_prompt=state["system_prompt"],
        )
    except AIConnectorError as exc:
        return {
            **state,
            "error_message": str(exc),
            "pipeline_status": "failed",
        }

    return {
        **state,
        "raw_audio_output": audio_b64,
        "transcript_input": transcript_in,
        "transcript_output": transcript_out,
        "pipeline_status": "answered",
    }


def format_voice_response(state: VoiceChatState) -> VoiceChatState:
    """트랜스크립트에서 슬라이드 참조를 추출하고 최종 음성 응답을 확정한다.

    오류 상태이면 무음 WAV 를 반환해 사용자가 빈 응답을 받지 않도록 한다.
    """
    if state.get("error_message"):
        return {
            **state,
            "audio_output": _empty_wav_b64(),
            "audio_format_out": "wav",
            "transcript_input": "",
            "transcript_output": (
                "죄송해요, 답변을 생성하는 중에 오류가 발생했어요. 잠시 후 다시 시도해 주세요."
            ),
            "referenced_slides": [],
            "pipeline_status": "error_handled",
        }

    from app.modules.Chat_V1.app.service import extract_referenced_slides

    transcript_out = state.get("transcript_output", "")
    refs = extract_referenced_slides(transcript_out)

    return {
        **state,
        "audio_output": state.get("raw_audio_output", ""),
        "audio_format_out": "wav",
        "referenced_slides": refs,
        "pipeline_status": "done",
    }


def _empty_wav_b64() -> str:
    """무음 WAV 파일을 base64 로 인코딩해 반환한다 (오류 폴백용)."""
    import base64
    import io
    import struct
    import wave

    sample_rate = 24000
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        silence = struct.pack(
            "<" + "h" * (sample_rate // 10), *([0] * (sample_rate // 10))
        )
        wf.writeframes(silence)
    return base64.b64encode(buf.getvalue()).decode("utf-8")
