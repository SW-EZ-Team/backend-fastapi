"""Silero VAD 래퍼 모듈.

torch.hub에서 Silero VAD 모델을 싱글톤으로 로드하고,
512 샘플(32ms) 청크 단위 음성 확률을 계산한다.
"""
from __future__ import annotations

import numpy as np
import torch

from app.modules.ASR_V1.pipeline.config import VAD_THRESHOLD

# Silero VAD 권장 청크 크기 — 16kHz에서 32ms
_CHUNK_SIZE: int = 512


class SileroVAD:
    """Silero VAD 클래스 싱글톤 래퍼."""

    _model: torch.nn.Module | None = None

    def __init__(self, threshold: float = VAD_THRESHOLD) -> None:
        """VAD 임계값 설정 및 상태 텐서 초기화."""
        self._threshold = threshold
        self._h: torch.Tensor | None = None
        self._c: torch.Tensor | None = None
        self._ensure_model()
        self.reset_state()

    @classmethod
    def _ensure_model(cls) -> None:
        """클래스 수준 싱글톤 모델 로드 — 최초 1회만 실행."""
        if cls._model is None:
            # Silero VAD v5 — jit 모델 로드 (torch.hub 자동 캐시)
            cls._model, _ = torch.hub.load(
                "snakers4/silero-vad",
                "silero_vad",
                trust_repo=True,
            )
            # 추론 전용 모드로 전환 (gradient 비활성화, BatchNorm/Dropout 고정)
            cls._model.train(False)

    def reset_state(self) -> None:
        """세션 간 h/c 상태 텐서 초기화 — 연결 시작 시 호출."""
        self._h = torch.zeros(2, 1, 64)
        self._c = torch.zeros(2, 1, 64)

    def process_chunk(self, chunk: np.ndarray) -> float:
        """512 샘플 numpy 청크 → 음성 확률(float) 반환.

        Silero는 float32 텐서와 h/c 상태를 요구한다.
        배치 차원 1을 추가해 (1, 512) 형태로 전달한다.
        """
        x = torch.from_numpy(chunk).float().unsqueeze(0)
        with torch.no_grad():
            prob, self._h, self._c = self._model(x, 16000, self._h, self._c)
        return float(prob.item())

    def is_speech(self, chunk: np.ndarray) -> bool:
        """청크가 음성인지 임계값 기준으로 판단."""
        return self.process_chunk(chunk) >= self._threshold

    @property
    def chunk_size(self) -> int:
        """VAD 처리 단위 샘플 수."""
        return _CHUNK_SIZE
