"""OpenAI ASR 폴백 커넥터.

Gemini ASR 커넥터(gemini_asr_connector.py)와 동일한 공개 인터페이스
(generate / supports)와 ASRResponse 스키마를 제공한다. Gemini ASR 장애 시
도메인 폴백 래퍼가 이 커넥터로 회로를 넘긴다. 동기 SDK 를 asyncio.to_thread 로
감싸 블로킹을 막는다(Gemini ASR 와 동일한 래핑 전략).
"""
from __future__ import annotations

import asyncio
import io
import os
import time

from common.audio_io import duration_sec, load_audio_from_bytes

from .._openai_common import build_openai_client
from ..errors import AIConnectorError, InferenceError
from ..schemas import ASRRequest, ASRResponse

_DEFAULT_MODEL = "gpt-4o-transcribe"
_TARGET_SR = 16000


class OpenAIASRConnector:
    """OpenAI 음성 전사를 기존 ASRResponse 로 변환한다."""

    name: str = "openai-asr"

    async def generate(self, request: ASRRequest) -> ASRResponse:
        """오디오 바이트를 한국어 전사 텍스트로 변환한다."""
        try:
            audio, sr = await asyncio.to_thread(
                load_audio_from_bytes, request.audio_bytes, _TARGET_SR
            )
            started_at = time.perf_counter()
            text = await asyncio.to_thread(
                self._transcribe, request.audio_bytes, request.language or "ko"
            )
        except AIConnectorError:
            raise
        except Exception as exc:
            raise InferenceError(f"OpenAI ASR 호출 실패: {exc}") from exc
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        return ASRResponse(
            text=text,
            language=request.language or "ko",
            duration_sec=duration_sec(audio, sr),
            latency_ms=latency_ms,
            model=self.name,
        )

    def supports(self, feature: str) -> bool:
        """OpenAI ASR 기능 플래그를 반환한다(Gemini ASR 와 동일 집합)."""
        return feature in {"basic", "transcription", "korean", "multimodal"}

    def _transcribe(self, audio_bytes: bytes, language: str) -> str:
        """동기 openai 호출을 실행하고 텍스트만 반환한다."""
        client, _openai = build_openai_client()
        model = os.getenv("OPENAI_ASR_MODEL", _DEFAULT_MODEL)
        # SDK 는 file 인자에 (이름, 바이트, MIME) 튜플 또는 file-like 를 받는다.
        # 업로드 바이트가 WAV 라고 가정하고 file-like 로 감싸 전달한다.
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "audio.wav"
        resp = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            language=language,
        )
        text = getattr(resp, "text", None)
        if not isinstance(text, str):
            raise InferenceError("OpenAI ASR 응답에서 text 를 찾지 못했습니다.")
        return text.strip()
