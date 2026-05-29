"""SileroVAD 단위 테스트.

실제 torch.hub 다운로드를 피하기 위해 모델을 mock으로 대체한다.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# torch 미설치 환경에서는 모듈 수집 단계에서 건너뜀
torch = pytest.importorskip("torch", reason="torch 미설치 — SileroVAD 테스트 건너뜀")

from app.modules.ASR_V1.pipeline.vad import SileroVAD


@pytest.fixture(autouse=True)
def reset_vad_singleton() -> None:
    """각 테스트 전에 싱글톤 모델 상태를 초기화한다."""
    SileroVAD._model = None
    yield
    SileroVAD._model = None


@pytest.fixture
def mock_vad_model() -> MagicMock:
    """Silero VAD torch 모델 mock — 고정 확률 0.9 반환."""
    model = MagicMock()
    # (prob, h, c) 반환 — prob은 0.9 텐서
    model.return_value = (
        torch.tensor(0.9),
        torch.zeros(2, 1, 64),
        torch.zeros(2, 1, 64),
    )
    return model


def test_is_speech_above_threshold(mock_vad_model: MagicMock) -> None:
    """확률이 임계값 이상이면 is_speech=True를 반환한다."""
    with patch.object(SileroVAD, "_ensure_model") as mock_ensure:
        SileroVAD._model = mock_vad_model
        mock_ensure.return_value = None
        vad = SileroVAD(threshold=0.5)
        chunk = np.zeros(512, dtype=np.float32)
        assert vad.is_speech(chunk) is True


def test_is_speech_below_threshold(mock_vad_model: MagicMock) -> None:
    """확률이 임계값 미만이면 is_speech=False를 반환한다."""
    # 낮은 확률 모델 — 0.2 반환
    mock_vad_model.return_value = (
        torch.tensor(0.2),
        torch.zeros(2, 1, 64),
        torch.zeros(2, 1, 64),
    )
    with patch.object(SileroVAD, "_ensure_model") as mock_ensure:
        SileroVAD._model = mock_vad_model
        mock_ensure.return_value = None
        vad = SileroVAD(threshold=0.5)
        chunk = np.zeros(512, dtype=np.float32)
        assert vad.is_speech(chunk) is False


def test_reset_state_reinitializes_tensors(mock_vad_model: MagicMock) -> None:
    """reset_state 후 h/c 텐서가 영행렬로 초기화된다."""
    with patch.object(SileroVAD, "_ensure_model") as mock_ensure:
        SileroVAD._model = mock_vad_model
        mock_ensure.return_value = None
        vad = SileroVAD(threshold=0.5)
        vad._h = torch.ones(2, 1, 64)
        vad.reset_state()
        assert torch.all(vad._h == 0)
        assert torch.all(vad._c == 0)


def test_chunk_size_is_512(mock_vad_model: MagicMock) -> None:
    """chunk_size 프로퍼티가 512를 반환한다."""
    with patch.object(SileroVAD, "_ensure_model") as mock_ensure:
        SileroVAD._model = mock_vad_model
        mock_ensure.return_value = None
        vad = SileroVAD()
        assert vad.chunk_size == 512


def test_process_chunk_returns_float(mock_vad_model: MagicMock) -> None:
    """process_chunk가 float를 반환한다."""
    with patch.object(SileroVAD, "_ensure_model") as mock_ensure:
        SileroVAD._model = mock_vad_model
        mock_ensure.return_value = None
        vad = SileroVAD(threshold=0.5)
        chunk = np.random.randn(512).astype(np.float32)
        result = vad.process_chunk(chunk)
        assert isinstance(result, float)
