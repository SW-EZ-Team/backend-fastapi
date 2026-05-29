"""ChapterStudio TTS V2 커넥터 — TTS_V2 모듈 파이프라인을 래핑한다.

TTS V1 의 HTTP 기반 합성을 대체해 로컬/Modal GPU 에서 직접 합성한다.
TTSConnector 프로토콜을 구현하므로 기존 ChapterStudio 파이프라인에서
drop-in 교체할 수 있다. synthesize() 는 단일 청크를 합성하고
WAV 파일을 저장한 뒤 경로와 재생 시간을 반환한다.
"""
from __future__ import annotations

import struct
from pathlib import Path
from time import time
from uuid import uuid4

import numpy as np

from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.common.config import (
    tts_output_dir,
    tts_ref_audio_path,
    tts_ref_text,
)
from app.modules.TTS_V2.connectors.tts_engine import TTSEngineSession
from app.modules.TTS_V2.processors.audio_postfx import postfx_pipeline
from common.logging import get_logger

_LOG = get_logger(__name__)

# 기본 출력 샘플레이트 — Qwen3-TTS 모델 기준
_OUTPUT_SR = 24000


class TTSV2Connector:
    """TTS V2 파이프라인을 ChapterStudio TTSConnector 프로토콜로 래핑한다.

    초기화 시 레퍼런스 오디오를 로드하고, synthesize() 호출마다
    TTSEngineSession 으로 합성 → postfx → WAV 저장 순으로 처리한다.
    """

    name = "tts_v2"

    def __init__(self) -> None:
        """레퍼런스 오디오 경로와 텍스트를 환경 변수에서 로드한다."""
        ref_path = tts_ref_audio_path()
        if ref_path is None or not ref_path.exists():
            raise ConnectorError("TTS_REF_AUDIO_PATH 가 설정되지 않았거나 파일이 없다.")
        self._ref_bytes: bytes = ref_path.read_bytes()
        self._ref_text: str = tts_ref_text() or ""
        self._output_dir: Path = tts_output_dir()
        _LOG.info("TTSV2Connector 초기화 완료 (ref=%s)", ref_path.name)

    async def synthesize(self, text: str, voice: str = "f1") -> dict[str, str | float]:
        """단일 텍스트를 합성해 WAV 파일 저장 후 결과를 반환한다.

        반환 형식은 TTSConnector 프로토콜과 동일:
        {"audio_url": "file:///...", "duration_sec": float}
        """
        audio_np, sample_rate = self._run_synthesis(text)
        audio_np = postfx_pipeline(audio_np, sample_rate)
        duration_sec = len(audio_np) / max(sample_rate, 1)
        audio_path = self._save_wav(audio_np, sample_rate, voice)
        return {
            "audio_url": audio_path.resolve().as_uri(),
            "duration_sec": float(duration_sec),
        }

    def _run_synthesis(self, text: str) -> tuple[np.ndarray, int]:
        """TTSEngineSession 으로 동기 합성을 수행한다."""
        with TTSEngineSession(
            ref_audio_bytes=self._ref_bytes,
            ref_text=self._ref_text,
            language="ko",
        ) as session:
            return session.synthesize_chunk(text)

    def _save_wav(self, audio_np: np.ndarray, sample_rate: int, voice: str) -> Path:
        """float32 numpy 배열을 16bit PCM WAV 로 저장한다."""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{int(time() * 1000)}_{_safe_token(voice)}_{uuid4().hex[:8]}.wav"
        path = self._output_dir / filename
        wav_bytes = _encode_wav(audio_np, sample_rate)
        path.write_bytes(wav_bytes)
        return path

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그를 반환한다."""
        return feature in {"tts_synthesis", "local_gpu", "postfx"}


def _encode_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    """float32 mono numpy 를 16bit PCM WAV bytes 로 인코딩한다."""
    # float32 → int16 변환
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    data = pcm.tobytes()
    # WAV 헤더 생성 (44바이트)
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM 형식
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        len(data),
    )
    return header + data


def _safe_token(value: str) -> str:
    """파일명에 안전한 토큰 문자열을 생성한다."""
    return "".join(c for c in value if c.isalnum() or c in {"-", "_"})[:32] or "voice"
