"""사용자 업로드 음성 파일 로컬 저장·로드·삭제를 담당한다.

저장 경로: app/modules/TTS_V2/user_voices/{user_id}/{profile_id}.wav
입력 오디오는 24000Hz mono WAV 로 정규화해 저장한다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from common.audio_io import (
    duration_sec as calc_duration,
    encode_wav_bytes,
    ensure_mono,
    load_audio_from_bytes,
)

# 사용자 음성 저장 루트 디렉터리
_USER_VOICES_DIR = Path(__file__).resolve().parent.parent / "user_voices"

# 정규화 저장 샘플레이트 (TTS ICL 모드 요구 사양)
_TARGET_SR = 24000


def _ensure_user_dir(user_id: str) -> Path:
    """사용자 전용 디렉터리가 없으면 생성 후 반환한다."""
    user_dir = _USER_VOICES_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def _profile_path(user_id: str, profile_id: str) -> Path:
    """프로필 파일 경로를 계산한다."""
    return _ensure_user_dir(user_id) / f"{profile_id}.wav"


def _normalize_to_wav(audio_bytes: bytes) -> tuple[bytes, int, float]:
    """입력 오디오를 24000Hz mono WAV 로 정규화한다.

    sample_rate 와 duration_sec 도 함께 반환해 DB 저장에 활용한다.
    """
    # librosa 를 통해 float32 numpy 로 읽고 정규화
    y, _ = load_audio_from_bytes(audio_bytes, target_sr=_TARGET_SR)
    mono: np.ndarray = ensure_mono(y)
    dur = calc_duration(mono, _TARGET_SR)
    wav_bytes = encode_wav_bytes(mono, _TARGET_SR)
    return wav_bytes, _TARGET_SR, dur


def save_audio(user_id: str, profile_id: str, audio_bytes: bytes) -> tuple[str, int, float]:
    """오디오를 정규화해 저장하고 (파일 경로, sample_rate, duration_sec) 를 반환한다.

    반환된 경로는 DB 의 ref_audio_url 컬럼에 저장한다.
    """
    wav_bytes, sample_rate, dur = _normalize_to_wav(audio_bytes)
    dest = _profile_path(user_id, profile_id)
    dest.write_bytes(wav_bytes)
    return str(dest), sample_rate, dur


def load_audio(ref_audio_url: str) -> bytes:
    """ref_audio_url 경로에서 WAV 바이트를 읽어 반환한다."""
    path = Path(ref_audio_url)
    if not path.exists():
        raise RuntimeError(f"레퍼런스 음성 파일이 없음: {ref_audio_url}")
    return path.read_bytes()


def delete_audio(ref_audio_url: str) -> None:
    """ref_audio_url 경로의 파일을 삭제한다. 파일이 없으면 조용히 넘어간다."""
    path = Path(ref_audio_url)
    if path.exists():
        path.unlink()
