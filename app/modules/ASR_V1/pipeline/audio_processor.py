"""오디오 프레임 처리 원자 모듈."""
from __future__ import annotations

import numpy as np

from app.modules.ASR_V1.pipeline.vad import SileroVAD

# Int16 → float32 정규화 스케일
_INT16_SCALE: float = 1.0 / 32768.0


def decode_pcm_int16(raw: bytes) -> np.ndarray:
    """PCM Int16LE 바이트를 float32 numpy 배열로 변환."""
    pcm16 = np.frombuffer(raw, dtype=np.int16)
    return pcm16.astype(np.float32) * _INT16_SCALE


def detect_speech_in_frame(audio_f32: np.ndarray, vad: SileroVAD) -> bool:
    """오디오 프레임을 VAD 청크 단위로 분할 처리해 음성 여부를 반환."""
    is_speech = False
    for offset in range(0, len(audio_f32), vad.chunk_size):
        chunk = audio_f32[offset : offset + vad.chunk_size]
        # 청크가 짧으면 zero-padding
        if len(chunk) < vad.chunk_size:
            chunk = np.pad(chunk, (0, vad.chunk_size - len(chunk)))
        is_speech = vad.is_speech(chunk)
    return is_speech
