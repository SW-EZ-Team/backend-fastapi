"""오디오 입출력 유틸.

업로드된 바이트 → 지정 샘플레이트 mono float32 numpy로 정규화,
또는 mono float32 numpy → 16-bit PCM WAV 바이트 인코딩을 담당한다.
커넥터가 자체적으로 librosa/scipy를 호출하지 않도록 여기서 한 번만 정리한다.
"""
from __future__ import annotations

import tempfile
from io import BytesIO
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.io import wavfile


def load_audio_from_bytes(
    data: bytes, target_sr: int = 16000
) -> tuple[np.ndarray, int]:
    """bytes 형태 오디오를 float32 numpy + 샘플레이트로 반환한다.

    fast path: librosa.load(BytesIO) — libsndfile 로 wav/flac/ogg 즉시 처리.
    fallback: 브라우저 MediaRecorder 가 내보내는 webm/opus 는 libsndfile 미지원이라
    LibsndfileError 가 난다. 이때 NamedTemporaryFile 로 디스크에 떨어뜨려
    librosa 의 audioread(ffmpeg) 경로로 재시도한다. ffmpeg 은 시스템에
    설치되어 있어야 한다 (Homebrew: `brew install ffmpeg`).
    """
    try:
        # 빠른 경로 — BytesIO 를 libsndfile 이 직접 처리 (wav/flac/ogg-vorbis)
        y, sr = librosa.load(BytesIO(data), sr=target_sr, mono=True)
    except sf.LibsndfileError:
        # 느린 경로 — webm/opus/m4a 등은 temp 파일 경로로 넘겨야 audioread(ffmpeg) 사용
        y, sr = _load_via_tempfile(data, target_sr)
    # 방어적으로 float32 강제 (librosa 기본이지만 버전별 차이 대비)
    return y.astype(np.float32, copy=False), sr


def _load_via_tempfile(data: bytes, target_sr: int) -> tuple[np.ndarray, int]:
    """디스크에 쓴 뒤 librosa.load(path) 로 audioread→ffmpeg 경로 유도.

    확장자를 .audio 로 중립 지정해 ffmpeg 이 컨테이너 헤더로 포맷을 자동 판별하게 한다.
    .webm 으로 고정하면 m4a/opus 등 실제 포맷과 불일치해 일부 ffmpeg 빌드에서
    컨테이너 미스매치 경고가 발생할 수 있다. tempfile 은 with 블록 종료 시 삭제된다.
    """
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        return librosa.load(Path(tmp.name), sr=target_sr, mono=True)


def ensure_mono(y: np.ndarray) -> np.ndarray:
    """2D(채널×샘플)로 들어오면 평균 내서 mono 1D로 변환."""
    # librosa.load(..., mono=True)를 쓰면 이미 1D지만,
    # 외부에서 직접 np.ndarray를 받을 경우를 위한 안전장치
    if y.ndim == 1:
        return y
    if y.ndim == 2:
        return y.mean(axis=0).astype(np.float32, copy=False)
    # 3D 이상은 정의되지 않음 — 호출자 책임
    raise ValueError(f"unsupported ndim={y.ndim} for mono conversion")


def duration_sec(y: np.ndarray, sample_rate: int) -> float:
    """샘플 수 / sr로 길이(초) 계산."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    return float(y.shape[-1]) / float(sample_rate)


def encode_wav_bytes(
    y: np.ndarray, sample_rate: int, bit_depth: int = 16
) -> bytes:
    """float32 mono 배열을 16-bit PCM WAV 바이트로 인코딩.

    브라우저 <audio> 태그 호환성을 위해 기본 16-bit PCM로 고정.
    clipping 방어를 위해 [-1, 1] 범위로 clip한 뒤 int16 변환.
    """
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if bit_depth != 16:
        # 16-bit 외 포맷은 현재 샌드박스 범위 밖 — 확장 시 soundfile.write 사용 검토
        raise ValueError(f"unsupported bit_depth={bit_depth}, only 16 supported")
    mono = ensure_mono(y)
    # [-1, 1] 외 값을 잘라내 int16 오버플로 방지 (MossFormer2 출력이 가끔 ±1 초과)
    clipped = np.clip(mono, -1.0, 1.0).astype(np.float32, copy=False)
    # float → int16 변환 — 32767 스케일 후 정수 반올림
    pcm16 = (clipped * 32767.0).astype(np.int16)
    buf = BytesIO()
    wavfile.write(buf, sample_rate, pcm16)
    return buf.getvalue()
