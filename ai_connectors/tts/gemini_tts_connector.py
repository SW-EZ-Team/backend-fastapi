"""Gemini TTS 커넥터.

google-genai 동기 SDK 를 asyncio.to_thread 로 감싸 기존 TTSConnector 인터페이스
(`synthesize(TTSRequest) -> TTSResponse`)에 맞춘다.
"""
from __future__ import annotations

import asyncio
import os
import time

from .._gemini_common import build_genai_client, pcm16_duration_sec, pcm16_mono_to_wav
from ..errors import AIConnectorError, InferenceError
from ..errors import TimeoutError as ConnectorTimeoutError
from ..tts_schemas import TTSRequest, TTSResponse

_DEFAULT_MODEL = "gemini-3.1-flash-tts-preview"
_DEFAULT_VOICE = "Kore"
_SAMPLE_RATE = 24000


class GeminiTTSConnector:
    """Gemini 멀티모달 TTS 를 기존 TTS 응답 스키마로 변환한다."""

    name: str = "gemini-tts"

    def __init__(self, timeout_sec: float = 300.0) -> None:
        self._timeout_sec = timeout_sec

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """음성 대본을 Gemini TTS 로 합성하고 WAV 바이트로 반환한다."""
        text = request.text.strip()
        if not text:
            raise InferenceError("합성할 텍스트가 비어 있습니다.")
        style = request.style.strip()
        started_at = time.perf_counter()
        try:
            pcm_data = await asyncio.wait_for(
                asyncio.to_thread(self._generate_pcm, text, style),
                timeout=self._timeout_sec,
            )
        except TimeoutError as exc:
            raise ConnectorTimeoutError(
                f"Gemini TTS 응답 시간이 초과되었습니다. ({self._timeout_sec}초)"
            ) from exc
        except AIConnectorError:
            raise
        except Exception as exc:
            raise InferenceError(f"Gemini TTS 호출 실패: {exc}") from exc
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        return TTSResponse(
            audio_bytes=pcm16_mono_to_wav(pcm_data, _SAMPLE_RATE),
            sample_rate=_SAMPLE_RATE,
            content_type="audio/wav",
            duration_sec=pcm16_duration_sec(pcm_data, _SAMPLE_RATE),
            latency_ms=latency_ms,
            char_count=len(text),
            model=self.name,
            auto_transcribed=False,
            resolved_ref_text=request.ref_text or "",
            ref_text_source="client" if request.ref_text else "not_used",
            retry_count=0,
            quality_cer=None,
            quality_reason="not_checked",
            segment_count=1,
        )

    def supports(self, feature: str) -> bool:
        """Gemini TTS 기능 플래그를 반환한다."""
        return feature in {"tts", "korean", "audio_tags", "long_text", "prebuilt_voice"}

    def _generate_pcm(self, text: str, style: str = "") -> bytes:
        """동기 google-genai 호출을 실행하고 PCM 바이트만 추출한다."""
        client, genai = build_genai_client()
        model = os.getenv("GEMINI_TTS_MODEL", _DEFAULT_MODEL)
        voice = os.getenv("GEMINI_TTS_VOICE", _DEFAULT_VOICE)
        resp = client.models.generate_content(
            model=model,
            contents=_styled_text(text, style),
            config=genai.types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=genai.types.SpeechConfig(
                    voice_config=genai.types.VoiceConfig(
                        prebuilt_voice_config=genai.types.PrebuiltVoiceConfig(
                            voice_name=voice
                        )
                    )
                ),
            ),
        )
        return _extract_pcm(resp)


def _styled_text(text: str, style: str) -> str:
    """스타일 지시가 있을 때만 자연어 안내를 앞에 붙여 기존 동작을 보존한다."""
    if not style:
        return text
    if "반말" in style:
        return f"친근한 또래 과외 선생님이 반말로 밝게 설명하듯 읽어줘:\n{text}"
    if "존댓말" in style:
        return f"다정하고 또렷한 과외 선생님이 존댓말로 차분히 설명하듯 읽어줘:\n{text}"
    return f"{style}:\n{text}"


def _extract_pcm(resp: object) -> bytes:
    """Gemini 응답에서 inline_data.data PCM 바이트를 꺼낸다."""
    try:
        data = resp.candidates[0].content.parts[0].inline_data.data
    except (AttributeError, IndexError, TypeError) as exc:
        raise InferenceError("Gemini TTS 응답에서 오디오 데이터를 찾지 못했습니다.") from exc
    if not isinstance(data, bytes):
        raise InferenceError("Gemini TTS 오디오 데이터가 bytes 형식이 아닙니다.")
    return data
