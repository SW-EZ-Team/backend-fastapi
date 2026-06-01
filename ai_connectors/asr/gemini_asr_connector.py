"""Gemini ASR 커넥터."""
from __future__ import annotations

import asyncio
import os
import time

from common.audio_io import duration_sec, load_audio_from_bytes

from .._gemini_common import build_genai_client
from ..errors import AIConnectorError, InferenceError
from ..schemas import ASRRequest, ASRResponse

_DEFAULT_MODEL = "gemini-3.5-flash"
_TARGET_SR = 16000
_PROMPT = "이 오디오를 한국어로 정확히 전사하라. 설명 없이 전사 텍스트만 출력."


class GeminiASRConnector:
    """Gemini 멀티모달 입력을 기존 ASRResponse 로 변환한다."""

    name: str = "gemini-asr"

    async def generate(self, request: ASRRequest) -> ASRResponse:
        """오디오 바이트를 한국어 전사 텍스트로 변환한다."""
        try:
            audio, sr = await asyncio.to_thread(
                load_audio_from_bytes, request.audio_bytes, _TARGET_SR
            )
            started_at = time.perf_counter()
            text = await asyncio.to_thread(self._transcribe, request.audio_bytes)
        except AIConnectorError:
            raise
        except Exception as exc:
            raise InferenceError(f"Gemini ASR 호출 실패: {exc}") from exc
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        return ASRResponse(
            text=text,
            language=request.language or "ko",
            duration_sec=duration_sec(audio, sr),
            latency_ms=latency_ms,
            model=self.name,
        )

    def supports(self, feature: str) -> bool:
        """Gemini ASR 기능 플래그를 반환한다."""
        return feature in {"basic", "transcription", "korean", "multimodal"}

    def _transcribe(self, audio_bytes: bytes) -> str:
        """동기 google-genai 호출을 실행하고 텍스트만 반환한다."""
        client, genai = build_genai_client()
        model = os.getenv("GEMINI_ASR_MODEL", _DEFAULT_MODEL)
        resp = client.models.generate_content(
            model=model,
            contents=[
                genai.types.Part.from_bytes(
                    data=audio_bytes,
                    mime_type="audio/wav",
                ),
                _PROMPT,
            ],
        )
        text = getattr(resp, "text", None)
        if not isinstance(text, str):
            raise InferenceError("Gemini ASR 응답에서 text 를 찾지 못했습니다.")
        return text.strip()
