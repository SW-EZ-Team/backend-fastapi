"""TTS 오디오 후처리 원자 모듈 (SRP: 오디오 신호 후처리만 담당).

silence trimming, volume normalize, fade in/out 세 함수가 독립적으로 조합 가능하다.
numpy만 사용하고 librosa/scipy는 필요한 곳에서만 지연 import한다.
"""
from __future__ import annotations

import numpy as np

# 침묵 판정 임계값 (RMS 에너지 기준)
_SILENCE_RMS_THRESHOLD = 0.01
# 침묵 최소 지속 샘플 수 (24kHz 기준 0.1초 = 2400샘플 — 단발성 노이즈 제거 방지)
_SILENCE_MIN_SAMPLES = 2400
# 페이드 인/아웃 길이 (기본 20ms)
_FADE_MS = 20


def trim_silence(
    audio: np.ndarray,
    sample_rate: int,
    threshold: float = _SILENCE_RMS_THRESHOLD,
    frame_ms: int = 10,
) -> np.ndarray:
    """앞뒤 침묵 구간을 잘라낸다.

    RMS 에너지가 threshold 미만인 frame 을 침묵으로 판정한다.
    전체가 침묵이면 원본을 그대로 반환한다 (빈 배열 방지).
    """
    frame_size = int(sample_rate * frame_ms / 1000)
    if len(audio) < frame_size:
        return audio

    # 프레임별 RMS 계산
    n_frames = len(audio) // frame_size
    frames = audio[: n_frames * frame_size].reshape(n_frames, frame_size)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))

    # 침묵이 아닌 첫/마지막 프레임 인덱스 탐색
    nonsilent = np.where(rms >= threshold)[0]
    if len(nonsilent) == 0:
        return audio

    start = nonsilent[0] * frame_size
    end = (nonsilent[-1] + 1) * frame_size
    return audio[start:end]


def volume_normalize(
    audio: np.ndarray,
    target_peak: float = 0.9,
) -> np.ndarray:
    """피크 진폭이 target_peak 가 되도록 스케일링한다.

    이미 클리핑된 신호(peak >= 1.0)도 안전하게 처리한다.
    전체가 무음이면 원본 반환.
    """
    peak = float(np.max(np.abs(audio)))
    if peak < 1e-9:
        return audio
    return (audio * (target_peak / peak)).astype(np.float32)


def apply_fade(
    audio: np.ndarray,
    sample_rate: int,
    fade_ms: int = _FADE_MS,
) -> np.ndarray:
    """시작/끝에 선형 페이드 인/아웃을 적용한다.

    fade_ms 가 오디오 길이의 절반 이상이면 fade_ms 를 자동 줄인다.
    """
    n_fade = min(int(sample_rate * fade_ms / 1000), len(audio) // 4)
    if n_fade <= 0:
        return audio

    result = audio.copy()
    # 페이드 인 — 0 → 1 선형
    result[:n_fade] *= np.linspace(0.0, 1.0, n_fade, dtype=np.float32)
    # 페이드 아웃 — 1 → 0 선형
    result[-n_fade:] *= np.linspace(1.0, 0.0, n_fade, dtype=np.float32)
    return result


def postprocess_audio(
    audio: np.ndarray,
    sample_rate: int,
    do_trim: bool = True,
    do_normalize: bool = True,
    do_fade: bool = True,
    target_peak: float = 0.9,
    fade_ms: int = _FADE_MS,
) -> np.ndarray:
    """trim → normalize → fade 순서로 후처리를 적용하는 파이프라인.

    각 단계는 do_* 플래그로 개별 활성화/비활성화할 수 있다.
    """
    result = audio
    if do_trim:
        result = trim_silence(result, sample_rate)
    if do_normalize:
        result = volume_normalize(result, target_peak=target_peak)
    if do_fade:
        result = apply_fade(result, sample_rate, fade_ms=fade_ms)
    return result
