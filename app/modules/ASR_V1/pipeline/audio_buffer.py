"""스트리밍 오디오 링 버퍼 모듈.

음성 청크를 순서대로 누적하고, VAD가 침묵을 감지했을 때
전체 버퍼를 추출해 ASR 배치 호출에 전달한다.
"""
from __future__ import annotations

import numpy as np

from app.modules.ASR_V1.pipeline.config import BUFFER_MAX_SEC, SAMPLE_RATE


class AudioBuffer:
    """스트리밍 음성 청크 누적 버퍼.

    최대 누적 시간을 초과하면 가장 오래된 샘플부터 자동 삭제한다.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        max_duration_sec: float = BUFFER_MAX_SEC,
    ) -> None:
        """버퍼 초기화."""
        self._sr = sample_rate
        self._max_samples = int(max_duration_sec * sample_rate)
        self._chunks: list[np.ndarray] = []
        self._total_samples: int = 0

    def append(self, chunk: np.ndarray) -> None:
        """음성 청크를 버퍼에 추가하고 최대 길이를 유지한다."""
        self._chunks.append(chunk.astype(np.float32, copy=False))
        self._total_samples += len(chunk)
        # 하드캡 초과 시 가장 오래된 청크부터 제거
        while self._total_samples > self._max_samples and self._chunks:
            removed = self._chunks.pop(0)
            self._total_samples -= len(removed)

    def extract_speech(self) -> np.ndarray:
        """전체 버퍼 numpy 반환 — 버퍼 내용은 유지 (비파괴)."""
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._chunks, axis=0)

    def consume_speech(self) -> np.ndarray:
        """전체 버퍼 numpy 반환 후 버퍼 초기화 (파괴적 읽기)."""
        audio = self.extract_speech()
        self.clear()
        return audio

    def clear(self) -> None:
        """버퍼 초기화."""
        self._chunks = []
        self._total_samples = 0

    def duration_sec(self) -> float:
        """현재 누적 오디오 길이(초)."""
        return self._total_samples / self._sr

    def is_empty(self) -> bool:
        """버퍼가 비어있는지 확인."""
        return self._total_samples == 0
