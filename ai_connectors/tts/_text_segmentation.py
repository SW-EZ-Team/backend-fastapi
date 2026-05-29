"""긴 TTS 입력을 안정적으로 나누는 유틸."""
from __future__ import annotations

import re

import numpy as np

from common.audio_io import ensure_mono
from common.pronunciation import normalize_pronunciation_terms

_SPACE_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"[^.!?。！？]+[.!?。！？]?")
_CLAUSE_RE = re.compile(r"[^,，;；]+[,，;；]?")


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
    pause_ms: int = 120,
) -> np.ndarray:
    """세그먼트 사이에 짧은 무음을 넣어 하나의 배열로 합친다."""
    if not segments:
        return np.zeros(0, dtype=np.float32)
    pause = np.zeros(int(sample_rate * pause_ms / 1000), dtype=np.float32)
    merged: list[np.ndarray] = []
    for index, segment in enumerate(segments):
        if index:
            merged.append(pause)
        merged.append(ensure_mono(segment).astype(np.float32, copy=False))
    return np.concatenate(merged)


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
