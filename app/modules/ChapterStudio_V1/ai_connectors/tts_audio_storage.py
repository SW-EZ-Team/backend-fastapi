from __future__ import annotations

from pathlib import Path
from time import time
from uuid import uuid4

from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.common.config import tts_media_url, tts_output_dir
from app.modules.ObjectStorage_V1 import (
    ObjectStorageConfigError,
    ObjectStorageUploadError,
    put_object,
    s3_enabled,
)


async def save_tts_wav_bytes(audio_bytes: bytes, voice: str) -> str:
    """TTS WAV bytes를 저장하고 브라우저가 GET 가능한 URL을 반환한다."""
    filename = _audio_filename(voice)
    if s3_enabled():
        return await _save_to_s3(audio_bytes, filename)
    return _save_to_local(audio_bytes, filename)


async def _save_to_s3(audio_bytes: bytes, filename: str) -> str:
    """S3 사용 환경에서는 공개 URL을 반환한다."""
    try:
        return await put_object(audio_bytes, key=f"tts/{filename}", content_type="audio/wav")
    except (ObjectStorageConfigError, ObjectStorageUploadError) as exc:
        raise ConnectorError(f"TTS 오디오 S3 저장 실패: {exc}") from exc


def _save_to_local(audio_bytes: bytes, filename: str) -> str:
    """로컬 저장 환경에서는 /media 하위 상대 URL을 반환한다."""
    output_dir = tts_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    _safe_output_path(output_dir, filename).write_bytes(audio_bytes)
    return tts_media_url(filename)


def _safe_output_path(output_dir: Path, filename: str) -> Path:
    """파일명이 출력 디렉터리 밖을 가리키지 않도록 방어한다."""
    base = output_dir.resolve()
    path = (base / filename).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ConnectorError("TTS 오디오 저장 경로가 출력 디렉터리 밖이다.") from exc
    return path


def _audio_filename(voice: str) -> str:
    return f"{int(time() * 1000)}_{_safe_token(voice)}_{uuid4().hex[:8]}.wav"


def _safe_token(value: str) -> str:
    return "".join(char for char in value if char.isalnum() or char in {"-", "_"})[:32] or "voice"


__all__ = ["save_tts_wav_bytes"]
