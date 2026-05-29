"""세그먼트 TTS 생성 루프."""
from __future__ import annotations

from typing import Any

import numpy as np

from ._generation_profile import GenerationProfile
from ._mlx_audio_runtime import run_generate
from ._text_segmentation import join_audio_segments


def synthesize_segments(
    model: Any,
    segments: list[str],
    ref_audio: np.ndarray,
    ref_sr: int,
    ref_text: str | None,
    language: str,
    speed: float,
    profile: GenerationProfile,
) -> tuple[np.ndarray, int]:
    """세그먼트별 오디오를 순서대로 생성해 하나로 합친다."""
    audio_segments: list[np.ndarray] = []
    sample_rate = 24000
    for segment in segments:
        segment_audio, sample_rate = run_generate(
            model,
            segment,
            ref_audio,
            ref_sr,
            ref_text,
            language,
            speed,
            profile.temperature,
            profile.top_k,
            profile.top_p,
            profile.repetition_penalty,
        )
        audio_segments.append(segment_audio)
    return join_audio_segments(audio_segments, sample_rate), sample_rate
