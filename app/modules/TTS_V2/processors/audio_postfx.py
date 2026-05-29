"""TTS V2 — 오디오 후처리 프로세서.

EBU R128 LUFS 정규화 + 피크 리미팅 + 크로스페이드 연결을 제공한다.
침묵 트림은 V1 _postprocess.trim_silence 를 재사용한다.
"""
from __future__ import annotations

import numpy as np

from ai_connectors.tts._postprocess import trim_silence, volume_normalize
from common.logging import get_logger

_LOG = get_logger(__name__)

# pyloudnorm 기본 블록 사이즈 (초) — ITU-R BS.1770-4 게이팅 최소 400ms
_LUFS_BLOCK_SIZE = 0.4
# 너무 짧은 오디오의 LUFS 측정 실패 시 fallback 을 위한 최소 샘플 길이 (0.4초 기준)
_MIN_SAMPLES_FOR_LUFS_METER = 9600  # 24000 * 0.4


def normalize_loudness(
    audio: np.ndarray,
    sample_rate: int,
    target_lufs: float = -16.0,
) -> np.ndarray:
    """pyloudnorm 으로 EBU R128 LUFS 정규화를 수행한다.

    오디오가 너무 짧아 측정 불가능하면 V1 volume_normalize 로 fallback 한다.
    """
    import pyloudnorm as pyln  # 지연 import — 테스트 환경 없어도 모듈 로드 허용
    if len(audio) == 0:
        return audio.astype(np.float32)
    if len(audio) < _MIN_SAMPLES_FOR_LUFS_METER:
        _LOG.debug("오디오가 짧아 volume_normalize fallback 사용 (samples=%d)", len(audio))
        return volume_normalize(audio, target_peak=0.9)
    meter = pyln.Meter(sample_rate, block_size=_LUFS_BLOCK_SIZE)
    # pyloudnorm 은 (samples,) 또는 (samples, channels) 수락
    audio_2d = audio.reshape(-1, 1) if audio.ndim == 1 else audio
    current_lufs = meter.integrated_loudness(audio_2d.astype(np.float64))
    if not np.isfinite(current_lufs):
        # 무음 등 측정 불가 신호 — fallback
        _LOG.debug("LUFS 측정값이 유효하지 않음 (%s), fallback", current_lufs)
        return volume_normalize(audio, target_peak=0.9)
    gain_db = target_lufs - current_lufs
    gain_linear = 10.0 ** (gain_db / 20.0)
    return (audio * gain_linear).astype(np.float32)


def limit_peak(audio: np.ndarray, peak_dbfs: float = -2.0) -> np.ndarray:
    """피크를 peak_dbfs 이하로 제한한다.

    현재 피크가 이미 목표 이하면 원본을 그대로 반환한다.
    빈 배열은 그대로 반환한다.
    """
    if len(audio) == 0:
        return audio.astype(np.float32)
    peak_linear = float(np.max(np.abs(audio)))
    if peak_linear < 1e-9:
        return audio  # 무음 신호
    current_dbfs = 20.0 * np.log10(peak_linear)
    if current_dbfs <= peak_dbfs:
        return audio
    target_peak_linear = 10.0 ** (peak_dbfs / 20.0)
    gain = target_peak_linear / peak_linear
    return (audio * gain).astype(np.float32)


def crossfade_segments(
    segments: list[np.ndarray],
    sample_rate: int,
    crossfade_ms: int = 50,
) -> np.ndarray:
    """인접 세그먼트를 선형 크로스페이드로 연결한다.

    세그먼트 수가 1 이하면 concat 또는 빈 배열을 반환한다.
    crossfade_ms 가 0 이면 단순 concatenate 를 수행한다.
    """
    if not segments:
        return np.array([], dtype=np.float32)
    if len(segments) == 1:
        return segments[0].astype(np.float32)
    n_fade = int(sample_rate * crossfade_ms / 1000)
    if n_fade <= 0:
        return np.concatenate(segments).astype(np.float32)
    return _apply_crossfade(segments, n_fade)


def _apply_crossfade(segments: list[np.ndarray], n_fade: int) -> np.ndarray:
    """n_fade 샘플 단위 선형 크로스페이드 적용 후 전체를 이어붙인다."""
    fade_out = np.linspace(1.0, 0.0, n_fade, dtype=np.float32)
    fade_in = np.linspace(0.0, 1.0, n_fade, dtype=np.float32)
    result = segments[0].astype(np.float32)
    for seg in segments[1:]:
        seg = seg.astype(np.float32)
        actual_n = min(n_fade, len(result), len(seg))
        if actual_n <= 0:
            result = np.concatenate([result, seg])
            continue
        # 앞 세그먼트 꼬리 + 뒤 세그먼트 머리를 겹쳐서 더한다
        overlap = result[-actual_n:] * fade_out[-actual_n:] + seg[:actual_n] * fade_in[:actual_n]
        result = np.concatenate([result[:-actual_n], overlap, seg[actual_n:]])
    return result


def postfx_pipeline(
    audio: np.ndarray,
    sample_rate: int,
    target_lufs: float = -16.0,
    peak_dbfs: float = -2.0,
    trim_threshold: float = 0.01,
) -> np.ndarray:
    """trim → loudness normalize → peak limit 순서로 후처리를 적용한다."""
    result = trim_silence(audio, sample_rate, threshold=trim_threshold)
    result = normalize_loudness(result, sample_rate, target_lufs=target_lufs)
    result = limit_peak(result, peak_dbfs=peak_dbfs)
    return result
