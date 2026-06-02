"""긴 TTS 입력을 안정적으로 나누는 유틸."""
from __future__ import annotations

import io
import os
import re
import wave

import numpy as np

from common.audio_io import encode_wav_bytes, ensure_mono
from common.pronunciation import normalize_pronunciation_terms
from ..tts_schemas import TTSResponse

_SPACE_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"[^.!?。！？]+[.!?。！？]?")
_CLAUSE_RE = re.compile(r"[^,，;；]+[,，;；]?")
_DEFAULT_PAUSE_MS = 60
_MIN_PAUSE_MS = 0
_MAX_PAUSE_MS = 500


def normalize_target_text(text: str) -> str:
    """개행과 연속 공백을 정리한 생성용 텍스트를 만든다."""
    collapsed = _SPACE_RE.sub(" ", text).strip()
    return normalize_pronunciation_terms(collapsed)


def split_tts_segments(text: str, max_chars: int = 120) -> list[str]:
    """문장 경계 우선으로 TTS 입력을 작은 세그먼트로 분할한다."""
    normalized = normalize_target_text(text)
    if not normalized:
        return []
    sentences = [chunk.strip() for chunk in _SENTENCE_RE.findall(normalized) if chunk.strip()]
    if not sentences:
        return _split_long_sentence(normalized, max_chars)
    segments: list[str] = []
    current = ""
    for sentence in sentences:
        for piece in _split_long_sentence(sentence, max_chars):
            candidate = piece if not current else f"{current} {piece}"
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                segments.append(current)
            current = piece
    if current:
        segments.append(current)
    return segments


def join_audio_segments(
    segments: list[np.ndarray],
    sample_rate: int,
    pause_ms: int | None = None,
) -> np.ndarray:
    """세그먼트 사이에 짧은 무음을 넣어 하나의 배열로 합친다."""
    if not segments:
        return np.zeros(0, dtype=np.float32)
    if pause_ms is None:
        resolved_pause_ms = default_segment_pause_ms()
    else:
        resolved_pause_ms = _clamp_pause_ms(pause_ms)
    pause = np.zeros(int(sample_rate * resolved_pause_ms / 1000), dtype=np.float32)
    merged: list[np.ndarray] = []
    for index, segment in enumerate(segments):
        if index:
            merged.append(pause)
        merged.append(ensure_mono(segment).astype(np.float32, copy=False))
    return np.concatenate(merged)


def merge_segment_responses(
    responses: list[TTSResponse],
    sample_rate: int,
    pause_ms: int | None = None,
) -> bytes:
    """세그먼트별 WAV 응답 사이에 무음을 넣어 단일 WAV bytes 로 병합한다."""
    arrays = [_decode_wav_bytes(resp.audio_bytes) for resp in responses]
    merged = join_audio_segments(arrays, sample_rate, pause_ms=pause_ms)
    return encode_wav_bytes(merged, sample_rate)


def default_segment_pause_ms() -> int:
    """TTS 세그먼트 사이 기본 무음 길이를 환경변수에서 읽는다."""
    raw_value = os.getenv("TTS_SEGMENT_PAUSE_MS", "").strip()
    if raw_value == "":
        return _DEFAULT_PAUSE_MS
    try:
        return _clamp_pause_ms(int(raw_value))
    except ValueError:
        return _DEFAULT_PAUSE_MS


def _decode_wav_bytes(audio_bytes: bytes) -> np.ndarray:
    """WAV bytes 를 float32 mono 배열로 변환한다."""
    with wave.open(io.BytesIO(audio_bytes)) as wf:
        raw = wf.readframes(wf.getnframes())
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32767.0
    return ensure_mono(pcm)


def _clamp_pause_ms(value: int) -> int:
    """이상한 환경값은 안전한 무음 범위 안으로 제한한다."""
    return max(_MIN_PAUSE_MS, min(_MAX_PAUSE_MS, value))


def _split_long_sentence(text: str, max_chars: int) -> list[str]:
    """문장 하나가 너무 길면 절 경계로 한 번 더 나눈다."""
    if len(text) <= max_chars:
        return [text.strip()]
    clauses = [chunk.strip() for chunk in _CLAUSE_RE.findall(text) if chunk.strip()]
    if len(clauses) <= 1:
        return _chunk_by_length(text, max_chars)
    pieces: list[str] = []
    current = ""
    for clause in clauses:
        candidate = clause if not current else f"{current} {clause}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            pieces.append(current)
        current = clause
    if current:
        pieces.append(current)
    return pieces


def _chunk_by_length(text: str, max_chars: int) -> list[str]:
    """절 경계도 없으면 길이 기준으로 강제 분할한다."""
    words = text.split(" ")
    pieces: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            pieces.append(current)
        current = word
    if current:
        pieces.append(current)
    return [piece.strip() for piece in pieces if piece.strip()]
