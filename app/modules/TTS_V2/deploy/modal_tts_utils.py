"""Modal TTS 서버의 작은 유틸리티 모음."""
from __future__ import annotations

import io
from dataclasses import dataclass
from urllib.parse import quote

import numpy as np
import soundfile as sf
from numpy.typing import NDArray


@dataclass(frozen=True)
class SynthesisMeta:
    """HTTP 헤더에 넣을 합성 메타데이터다."""

    sample_rate: int
    duration_sec: float
    latency_ms: float
    ref_text_used: str
    x_vector_only: bool


def encode_wav(audio: NDArray[np.float32], sample_rate: int) -> bytes:
    """float 배열을 16-bit PCM WAV로 인코딩한다."""
    clipped = np.clip(audio.astype(np.float32, copy=False), -1.0, 1.0)
    buf = io.BytesIO()
    sf.write(buf, clipped, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def response_headers(meta: SynthesisMeta, text: str) -> dict[str, str]:
    """기존 qwen3_tts_modal_connector가 읽는 응답 헤더를 만든다."""
    return {
        "x-sample-rate": str(meta.sample_rate),
        "x-duration-sec": f"{meta.duration_sec:.3f}",
        "x-latency-ms": f"{meta.latency_ms:.1f}",
        "x-char-count": str(len(text)),
        "x-auto-transcribed": "false",
        "x-ref-text-used": quote(meta.ref_text_used),
        "x-ref-text-source": "client" if meta.ref_text_used else "empty_fallback",
        "x-retry-count": "0",
        "x-quality-reason": "not_checked",
        "x-segment-count": "1",
    }


def normalize_language(language: str) -> str:
    """내부 lang_code 표기를 qwen-tts 패키지 표기로 변환한다."""
    key = language.strip().lower()
    mapping = {
        "": "Korean",
        "auto": "Korean",
        "ko": "Korean",
        "kor": "Korean",
        "korean": "Korean",
        "en": "English",
        "eng": "English",
        "english": "English",
        "zh": "Chinese",
        "chinese": "Chinese",
        "ja": "Japanese",
        "japanese": "Japanese",
    }
    return mapping.get(key, language)
