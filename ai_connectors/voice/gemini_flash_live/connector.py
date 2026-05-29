"""Gemini Flash Live 음성 커넥터.

google-genai SDK 의 Live API 를 사용해 음성 입력 → 음성 출력을 처리한다.
ASR + 생성 + TTS 가 단일 모델에서 처리되므로 별도 파이프라인 불필요.
벤더 예외를 ai_connectors.errors 공통 예외로 번역한다.
"""
from __future__ import annotations

import asyncio
import base64
import io
import struct
import wave

from ai_connectors.errors import (
    AuthError,
    ConnectorError,
    RateLimitError,
)
from ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from ai_connectors.voice.gemini_flash_live.config import (
    gemini_api_key,
    gemini_flash_live_model,
    gemini_flash_live_timeout_sec,
)
from ai_connectors.voice.gemini_flash_live.schemas import VoiceRequest, VoiceResponse


class GeminiFlashLiveConnector:
    """Google Gemini Flash Live 음성 대화 커넥터.

    google-genai SDK 를 감싸고 벤더 예외를 공통 예외 계층으로 번역한다.
    음성 입력을 받아 음성 응답과 트랜스크립트를 함께 반환한다.
    """

    name = "gemini_flash_live"

    def __init__(self) -> None:
        # API 키 미설정 시 생성 단계에서 즉시 실패 — 런타임 AuthError 방지
        api_key = gemini_api_key()
        if api_key is None:
            raise AuthError(
                "GEMINI_API_KEY 또는 GOOGLE_API_KEY 가 설정되지 않았다."
            )
        self._api_key = api_key
        self._model = gemini_flash_live_model()
        self._timeout = gemini_flash_live_timeout_sec()

    async def voice_chat(self, request: VoiceRequest) -> VoiceResponse:
        """음성 입력을 받아 음성 응답과 트랜스크립트를 반환한다.

        Gemini Flash Live 는 ASR + 생성 + TTS 를 하나의 API 호출로 처리한다.
        오류 발생 시 ai_connectors.errors 공통 예외로 번역해 올린다.
        """
        try:
            return await asyncio.wait_for(
                self._call_live_api(request),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            raise ConnectorTimeoutError(
                f"Gemini Flash Live 응답 타임아웃 ({self._timeout}초)"
            ) from exc
        except ConnectorError:
            raise
        except AuthError:
            raise
        except RateLimitError:
            raise

    def supports(self, feature: str) -> bool:
        """지원하는 기능 플래그를 반환한다."""
        return feature in {"voice_chat", "asr", "tts", "korean", "multimodal"}

    async def _call_live_api(self, request: VoiceRequest) -> VoiceResponse:
        """Gemini Live API 를 실제로 호출한다.

        google-genai SDK 의 aio.live.connect 컨텍스트를 사용하며
        단일 턴(질문-응답) 방식으로 동작한다.
        """
        try:
            import google.genai as genai
            from google.genai import types as genai_types
        except ImportError as exc:
            raise ConnectorError(
                "google-genai 패키지가 설치되지 않았다. "
                "`uv pip install google-genai` 실행 필요"
            ) from exc

        client = genai.Client(api_key=self._api_key)
        audio_bytes = base64.b64decode(request.audio_data)
        mime_type = _audio_mime_type(request.audio_format)

        config = genai_types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=request.system_prompt or None,
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name="Kore"
                    )
                )
            ),
        )

        transcript_input = ""
        transcript_output = ""
        output_audio_chunks: list[bytes] = []

        async with client.aio.live.connect(
            model=self._model, config=config
        ) as session:
            await session.send(
                input=genai_types.LiveClientRealtimeInput(
                    media_chunks=[
                        genai_types.Blob(data=audio_bytes, mime_type=mime_type)
                    ]
                ),
            )

            async for response in session.receive():
                if response.server_content is None:
                    continue
                content = response.server_content

                # 트랜스크립트 수집 (입력/출력 모두)
                if content.input_transcription is not None:
                    transcript_input += content.input_transcription.text or ""
                if content.output_transcription is not None:
                    transcript_output += content.output_transcription.text or ""

                # 오디오 청크 수집
                if content.model_turn is not None:
                    for part in content.model_turn.parts:
                        if part.inline_data is not None:
                            output_audio_chunks.append(part.inline_data.data)

                # 응답 완료 신호 감지
                if content.turn_complete:
                    break

        raw_audio = b"".join(output_audio_chunks)
        wav_bytes = _encode_pcm_to_wav(raw_audio, sample_rate=24000)
        audio_b64 = base64.b64encode(wav_bytes).decode("utf-8")

        return VoiceResponse(
            audio_data=audio_b64,
            audio_format="wav",
            transcript_input=transcript_input.strip(),
            transcript_output=transcript_output.strip(),
            referenced_slides=[],  # 슬라이드 참조는 voice_service 레이어에서 파싱
        )


def _audio_mime_type(fmt: str) -> str:
    """오디오 포맷 문자열을 MIME 타입으로 변환한다."""
    mapping = {
        "webm": "audio/webm",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
        "mp4": "audio/mp4",
        "ogg": "audio/ogg",
    }
    return mapping.get(fmt.lower(), "audio/webm")


def _encode_pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000) -> bytes:
    """원시 PCM 바이트를 WAV 파일로 인코딩한다.

    Gemini Flash Live 는 16-bit signed PCM 을 반환한다.
    WAV 헤더를 붙여 범용 오디오 플레이어가 재생할 수 있도록 한다.
    """
    if not pcm_data:
        return _empty_wav(sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)   # 모노
        wf.setsampwidth(2)   # 16-bit = 2바이트
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def _empty_wav(sample_rate: int) -> bytes:
    """비어 있는 WAV 파일 바이트를 반환한다 (무음 응답 폴백용)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # 0.1초 분량의 무음
        silence = struct.pack("<" + "h" * (sample_rate // 10), *([0] * (sample_rate // 10)))
        wf.writeframes(silence)
    return buf.getvalue()
