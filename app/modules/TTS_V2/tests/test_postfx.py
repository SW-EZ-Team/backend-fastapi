"""TTS V2 — 오디오 후처리 단위 테스트.

audio_postfx 모듈의 각 함수와 파이프라인 전체를 검증한다.
실제 ML 모델 없이 numpy 신호만으로 동작해야 한다.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.modules.TTS_V2.processors.audio_postfx import (
    crossfade_segments,
    limit_peak,
    normalize_loudness,
    postfx_pipeline,
)

# 테스트용 기본 샘플레이트 (24kHz — Qwen3-TTS 출력 기준)
_SR = 24000

# LUFS 측정 최소 길이 기준을 넘기기 위해 1초 분량 사용
_1SEC = _SR


def _sine(freq: float = 1000.0, duration_sec: float = 1.0, amplitude: float = 0.5) -> np.ndarray:
    """지정 주파수·진폭의 사인파 생성 헬퍼."""
    t = np.linspace(0.0, duration_sec, int(_SR * duration_sec), endpoint=False)
    return (amplitude * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


class TestNormalizeLoudness:
    """normalize_loudness — LUFS 정규화 테스트."""

    def test_output_is_float32(self) -> None:
        """출력 배열이 float32 여야 한다."""
        audio = _sine(amplitude=0.5)
        result = normalize_loudness(audio, _SR, target_lufs=-16.0)
        assert result.dtype == np.float32

    def test_shape_preserved(self) -> None:
        """입력 배열과 출력 배열의 shape 이 같아야 한다."""
        audio = _sine(amplitude=0.3, duration_sec=1.0)
        result = normalize_loudness(audio, _SR, target_lufs=-16.0)
        assert result.shape == audio.shape

    def test_louder_signal_attenuated(self) -> None:
        """매우 큰 신호는 정규화 후 피크가 줄어야 한다."""
        audio = _sine(amplitude=0.95)
        result = normalize_loudness(audio, _SR, target_lufs=-23.0)
        # 더 낮은 LUFS 목표 → 게인이 낮아짐 → 피크 감소
        assert float(np.max(np.abs(result))) < float(np.max(np.abs(audio)))

    def test_short_audio_fallback_no_crash(self) -> None:
        """너무 짧은 오디오는 fallback 처리되어 오류 없이 반환되어야 한다."""
        short_audio = np.zeros(100, dtype=np.float32)
        result = normalize_loudness(short_audio, _SR, target_lufs=-16.0)
        # fallback 은 volume_normalize 이므로 silence 는 그대로 반환
        assert result.shape == short_audio.shape

    def test_silence_no_crash(self) -> None:
        """무음 오디오가 들어와도 오류가 나지 않아야 한다."""
        silent = np.zeros(_1SEC, dtype=np.float32)
        result = normalize_loudness(silent, _SR, target_lufs=-16.0)
        assert result is not None
        assert result.shape == silent.shape

    def test_different_target_lufs_change_gain(self) -> None:
        """target_lufs 가 다르면 출력 게인이 달라야 한다."""
        audio = _sine(amplitude=0.1)
        r_loud = normalize_loudness(audio, _SR, target_lufs=-6.0)
        r_quiet = normalize_loudness(audio, _SR, target_lufs=-23.0)
        peak_loud = float(np.max(np.abs(r_loud)))
        peak_quiet = float(np.max(np.abs(r_quiet)))
        assert peak_loud > peak_quiet


class TestLimitPeak:
    """limit_peak — 피크 리미터 테스트."""

    def test_peak_below_target_unchanged(self) -> None:
        """이미 피크가 목표 이하이면 원본과 동일해야 한다."""
        audio = _sine(amplitude=0.1)  # 피크 ~0.1 → -20 dBFS
        result = limit_peak(audio, peak_dbfs=-2.0)
        np.testing.assert_array_equal(result, audio)

    def test_peak_exceeds_target_reduced(self) -> None:
        """피크가 목표를 초과하면 목표 dBFS 이하로 줄어야 한다."""
        audio = _sine(amplitude=0.99)  # 피크 ~-0.087 dBFS
        result = limit_peak(audio, peak_dbfs=-6.0)
        peak_linear = float(np.max(np.abs(result)))
        target_linear = 10.0 ** (-6.0 / 20.0)
        assert peak_linear <= target_linear + 1e-6

    def test_output_dtype_float32(self) -> None:
        """출력 배열이 float32 여야 한다."""
        audio = _sine(amplitude=0.8)
        result = limit_peak(audio, peak_dbfs=-2.0)
        assert result.dtype == np.float32

    def test_silence_returned_unchanged(self) -> None:
        """무음 신호는 원본을 그대로 반환한다."""
        silent = np.zeros(1000, dtype=np.float32)
        result = limit_peak(silent, peak_dbfs=-2.0)
        np.testing.assert_array_equal(result, silent)

    def test_shape_preserved(self) -> None:
        """출력 shape 이 입력과 동일해야 한다."""
        audio = _sine(amplitude=0.5, duration_sec=0.5)
        result = limit_peak(audio, peak_dbfs=-2.0)
        assert result.shape == audio.shape


class TestCrossfadeSegments:
    """crossfade_segments — 크로스페이드 연결 테스트."""

    def test_empty_input_returns_empty(self) -> None:
        """빈 목록 입력 시 빈 배열을 반환해야 한다."""
        result = crossfade_segments([], _SR, crossfade_ms=50)
        assert result.shape == (0,)

    def test_single_segment_returned_as_is(self) -> None:
        """세그먼트 하나만 있으면 그대로 반환해야 한다."""
        seg = _sine(duration_sec=0.5)
        result = crossfade_segments([seg], _SR, crossfade_ms=50)
        np.testing.assert_array_almost_equal(result, seg.astype(np.float32))

    def test_two_segments_output_shorter_than_sum(self) -> None:
        """두 세그먼트를 크로스페이드하면 단순 concat 보다 짧아야 한다."""
        seg_a = _sine(freq=440.0, duration_sec=0.5)
        seg_b = _sine(freq=880.0, duration_sec=0.5)
        concatenated = len(seg_a) + len(seg_b)
        result = crossfade_segments([seg_a, seg_b], _SR, crossfade_ms=50)
        # crossfade 로 n_fade 샘플만큼 겹치므로 총 길이가 줄어야 함
        assert len(result) < concatenated

    def test_zero_crossfade_equals_concat(self) -> None:
        """crossfade_ms=0 이면 단순 concatenate 와 동일해야 한다."""
        seg_a = _sine(freq=440.0, duration_sec=0.2)
        seg_b = _sine(freq=880.0, duration_sec=0.2)
        expected = np.concatenate([seg_a, seg_b]).astype(np.float32)
        result = crossfade_segments([seg_a, seg_b], _SR, crossfade_ms=0)
        np.testing.assert_array_almost_equal(result, expected)

    def test_overlap_region_blended(self) -> None:
        """크로스페이드 오버랩 구간 중앙값이 두 세그먼트 중간값이어야 한다.

        fade_out=0.5, fade_in=0.5 시점에서 두 세그먼트의 진폭이 혼합된다.
        """
        # 상수 신호로 단순 계산 가능
        seg_a = np.ones(1000, dtype=np.float32)
        seg_b = np.zeros(1000, dtype=np.float32)
        n_fade = int(_SR * 10 / 1000)  # 10ms
        result = crossfade_segments([seg_a, seg_b], _SR, crossfade_ms=10)
        # 오버랩 시작 위치 — 원래 seg_a 끝에서 n_fade 전부터
        overlap_start = len(seg_a) - n_fade
        midpoint = overlap_start + n_fade // 2
        # 중간 지점 값이 0~1 사이여야 함 (혼합 결과)
        assert 0.0 < float(result[midpoint]) < 1.0

    def test_output_float32(self) -> None:
        """출력 배열이 float32 여야 한다."""
        segs = [_sine(duration_sec=0.1), _sine(freq=880.0, duration_sec=0.1)]
        result = crossfade_segments(segs, _SR, crossfade_ms=20)
        assert result.dtype == np.float32


class TestPostfxPipeline:
    """postfx_pipeline — 엔드투엔드 파이프라인 테스트."""

    def test_output_is_float32(self) -> None:
        """출력이 float32 여야 한다."""
        audio = _sine(amplitude=0.5)
        result = postfx_pipeline(audio, _SR)
        assert result.dtype == np.float32

    def test_peak_within_limit(self) -> None:
        """파이프라인 통과 후 피크가 peak_dbfs 이하여야 한다."""
        audio = _sine(amplitude=0.99)
        peak_dbfs = -2.0
        result = postfx_pipeline(audio, _SR, peak_dbfs=peak_dbfs)
        peak_linear = float(np.max(np.abs(result)))
        target_linear = 10.0 ** (peak_dbfs / 20.0)
        assert peak_linear <= target_linear + 1e-5

    def test_silence_no_crash(self) -> None:
        """무음 오디오도 오류 없이 처리되어야 한다."""
        silent = np.zeros(_1SEC, dtype=np.float32)
        result = postfx_pipeline(silent, _SR)
        assert result is not None

    def test_empty_array_no_crash(self) -> None:
        """빈 배열은 trim_silence 에서 그대로 반환되고 이후 처리도 무사해야 한다."""
        # trim_silence 가 빈 배열을 받으면 즉시 반환, 이후 volume_normalize/limit_peak 도 무해
        audio = np.array([], dtype=np.float32)
        result = postfx_pipeline(audio, _SR)
        assert isinstance(result, np.ndarray)

    def test_short_audio_no_crash(self) -> None:
        """매우 짧은 오디오(0.1초)도 오류 없이 처리되어야 한다."""
        short = _sine(duration_sec=0.1, amplitude=0.3)
        result = postfx_pipeline(short, _SR)
        assert result is not None

    def test_pipeline_reduces_silence_prefix(self) -> None:
        """앞에 묵음이 붙은 신호는 트림 후 길이가 줄어야 한다."""
        silence = np.zeros(int(_SR * 0.2), dtype=np.float32)  # 0.2초 묵음
        signal = _sine(duration_sec=0.8, amplitude=0.5)
        padded = np.concatenate([silence, signal])
        result = postfx_pipeline(padded, _SR, trim_threshold=0.01)
        # 트림으로 앞 묵음이 제거되어 길이가 줄어야 함
        assert len(result) < len(padded)
