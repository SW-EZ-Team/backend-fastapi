"""OpenAI TTS 폴백 커넥터.

Gemini TTS 커넥터(gemini_tts_connector.py)와 동일한 공개 인터페이스
(synthesize / supports)와 TTSResponse 스키마를 제공한다. Gemini TTS 장애 시
도메인 폴백 래퍼가 이 커넥터로 회로를 넘긴다. 동기 SDK 를 asyncio.to_thread 로
감싸고 asyncio.wait_for 로 타임아웃을 거는 전략을 Gemini TTS 그대로 따른다.

OpenAI TTS 는 response_format="wav" 로 WAV 바이트를 직접 돌려준다. PCM 길이를 알 수
없으므로 wav 헤더에서 재생 시간을 계산한다(_openai_common.wav_duration_sec).
"""
from __future__ import annotations

import asyncio
import os
import time

from .._openai_common import build_openai_client, wav_duration_sec
from ..errors import AIConnectorError, InferenceError
from ..errors import TimeoutError as ConnectorTimeoutError
from ..tts_schemas import TTSRequest, TTSResponse

_DEFAULT_MODEL = "gpt-4o-mini-tts"
_DEFAULT_VOICE = "alloy"
_SAMPLE_RATE = 24000


class OpenAITTSConnector:
    """OpenAI 음성 합성을 기존 TTS 응답 스키마로 변환한다."""

    name: str = "openai-tts"

    def __init__(self, timeout_sec: float = 300.0) -> None:
        self._timeout_sec = timeout_sec

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """음성 대본을 OpenAI TTS 로 합성하고 WAV 바이트로 반환한다."""
        text = request.text.strip()
        if not text:
            raise InferenceError("합성할 텍스트가 비어 있습니다.")
        style = request.style.strip()
        started_at = time.perf_counter()
        try:
            wav_data = await asyncio.wait_for(
                asyncio.to_thread(self._generate_wav, text, style),
                timeout=self._timeout_sec,
            )
        except TimeoutError as exc:
            raise ConnectorTimeoutError(
                f"OpenAI TTS 응답 시간이 초과되었습니다. ({self._timeout_sec}초)"
            ) from exc
        except AIConnectorError:
            raise
        except Exception as exc:
            raise InferenceError(f"OpenAI TTS 호출 실패: {exc}") from exc
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        return TTSResponse(
            audio_bytes=wav_data,
            sample_rate=_SAMPLE_RATE,
            content_type="audio/wav",
            duration_sec=wav_duration_sec(wav_data),
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
        """OpenAI TTS 기능 플래그를 반환한다(Gemini TTS 와 동일 집합)."""
        return feature in {"tts", "korean", "audio_tags", "long_text", "prebuilt_voice"}

    def _generate_wav(self, text: str, style: str = "") -> bytes:
        """동기 openai 호출을 실행하고 WAV 바이트만 반환한다."""
        client, _openai = build_openai_client()
        model = os.getenv("OPENAI_TTS_MODEL", _DEFAULT_MODEL)
        voice = os.getenv("OPENAI_TTS_VOICE", _DEFAULT_VOICE)
        kwargs: dict[str, object] = {
            "model": model,
            "voice": voice,
            "input": text,
            "response_format": "wav",
        }
        # Gemini 의 말투 힌트(반말/존댓말)를 instructions 로 전달한다.
        # 구버전 SDK 가 instructions 를 모르면 TypeError 를 던지므로 우아하게 무시한다.
        instructions = _style_instructions(style)
        if instructions:
            try:
                resp = client.audio.speech.create(instructions=instructions, **kwargs)
            except TypeError:
                resp = client.audio.speech.create(**kwargs)
        else:
            resp = client.audio.speech.create(**kwargs)
        return _extract_wav(resp)


def _style_instructions(style: str) -> str:
    """스타일 지시를 OpenAI TTS instructions 자연어 안내로 변환한다.

    Gemini TTS 의 _styled_text 와 동일한 말투 매핑을 유지한다.
    """
    if not style:
        return ""
    if "반말" in style:
        return "친근한 또래 과외 선생님이 반말로 밝게 설명하듯 읽어줘."
    if "존댓말" in style:
        return "다정하고 또렷한 과외 선생님이 존댓말로 차분히 설명하듯 읽어줘."
    return style


def _extract_wav(resp: object) -> bytes:
    """OpenAI 음성 응답에서 WAV 바이트를 꺼낸다."""
    # SDK 는 HttpxBinaryResponseContent 를 돌려준다 — .content 가 바이트다.
    data = getattr(resp, "content", resp)
    if not isinstance(data, (bytes, bytearray)):
        raise InferenceError("OpenAI TTS 응답에서 오디오 데이터를 찾지 못했습니다.")
    return bytes(data)
