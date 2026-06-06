"""ChapterStudio 레슨 TTS 용 Gemini 어댑터.

시스템 A(ai_connectors/tts/gemini_tts_connector.py)의 GeminiTTSConnector 는
`synthesize(TTSRequest) -> TTSResponse` 인터페이스를 쓰고, ChapterStudio 의
TTSConnector(base.py)는 `synthesize(text, voice) -> dict` 인터페이스를 쓴다.
두 인터페이스가 달라 이 얇은 어댑터로 시스템 A 커넥터를 감싸 ChapterStudio
파이프라인에서 drop-in 으로 쓸 수 있게 한다.

합성 결과 WAV 바이트는 tts_audio_storage.save_tts_wav_bytes 로 저장하고
브라우저가 GET 가능한 URL 과 재생 시간을 dict 로 반환한다.
"""
from __future__ import annotations

from ai_connectors.tts.gemini_tts_connector import GeminiTTSConnector
from ai_connectors.tts_schemas import TTSRequest

from app.modules.ChapterStudio_V1.ai_connectors.tts_audio_storage import save_tts_wav_bytes


class GeminiTTSChapterConnector:
    """시스템 A Gemini TTS 를 ChapterStudio TTSConnector 프로토콜로 변환한다."""

    name = "gemini_tts"

    def __init__(self) -> None:
        """내부에 시스템 A Gemini TTS 커넥터를 보유한다.

        Gemini 는 사전 정의 음성(prebuilt voice)을 쓰므로 레퍼런스 오디오
        클로닝이 필요 없다. 모델/음성은 시스템 A 커넥터가 .env 로 읽는다.
        """
        self._inner = GeminiTTSConnector()

    async def synthesize(self, text: str, voice: str = "f1") -> dict[str, str | float]:
        """단일 텍스트를 Gemini 로 합성해 WAV 저장 후 URL/길이를 반환한다.

        voice 인자는 ChapterStudio 튜터 식별자다. Gemini 는 prebuilt voice 를
        쓰므로 voice 를 말투 힌트(style)로 전달해 어댑터를 벤더 중립으로 둔다.
        ref_audio_bytes 는 시스템 A 스키마의 필수 필드지만 Gemini 경로에서
        사용되지 않으므로 빈 바이트를 넣는다.
        """
        response = await self._inner.synthesize(
            TTSRequest(text=text, ref_audio_bytes=b"", style=voice)
        )
        return {
            "audio_url": await save_tts_wav_bytes(response.audio_bytes, voice),
            "duration_sec": float(response.duration_sec),
        }

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그를 시스템 A 커넥터에 위임한다."""
        return self._inner.supports(feature)
