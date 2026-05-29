"""ASR 엔진 래퍼 모듈.

기존 ASRConnector를 지연 로드하고, numpy 오디오를 WAV 바이트로
변환한 뒤 ASRRequest로 래핑해 배치 호출한다.
"""
from __future__ import annotations

import numpy as np

from ai_connectors.base import ASRConnector
from ai_connectors.registry import get_asr_connector
from ai_connectors.schemas import ASRRequest, ASRResponse
from common.audio_io import encode_wav_bytes
from app.modules.ASR_V1.pipeline.config import ASR_MODEL, SAMPLE_RATE


class ASREngine:
    """numpy 오디오 → ASRResponse 변환 엔진.

    커넥터는 최초 transcribe 호출 시 지연 로드된다.
    """

    def __init__(self, model_name: str = ASR_MODEL) -> None:
        """모델 이름 저장 — 커넥터 인스턴스는 지연 생성."""
        self._model_name = model_name
        self._connector: ASRConnector | None = None

    def _ensure_connector(self) -> ASRConnector:
        """커넥터 지연 로드 — 최초 호출 시 인스턴스 생성."""
        if self._connector is None:
            self._connector = get_asr_connector(self._model_name)
        return self._connector

    async def transcribe(
        self,
        audio_np: np.ndarray,
        sr: int = SAMPLE_RATE,
        lang: str = "ko",
    ) -> ASRResponse:
        """numpy 오디오를 WAV 바이트로 변환 후 ASR 추론을 실행한다.

        Args:
            audio_np: float32 mono numpy 배열
            sr: 샘플레이트 (기본 16000Hz)
            lang: 전사 언어 코드

        Returns:
            ASRResponse: 전사 결과 (text, latency_ms, duration_sec 등)
        """
        connector = self._ensure_connector()
        wav_bytes = encode_wav_bytes(audio_np, sr)
        request = ASRRequest(
            audio_bytes=wav_bytes,
            language=lang,
            sample_rate=sr,
        )
        return await connector.generate(request)
