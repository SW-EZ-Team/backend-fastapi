"""AudioBuffer 단위 테스트.

버퍼 누적, 비파괴/파괴적 읽기, 하드캡 초과, 빈 버퍼 처리를 검증한다.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.modules.ASR_V1.pipeline.audio_buffer import AudioBuffer


@pytest.fixture
def buf() -> AudioBuffer:
    """기본 샘플레이트(16000), 최대 1초 버퍼."""
    return AudioBuffer(sample_rate=16000, max_duration_sec=1.0)


def test_append_and_extract(buf: AudioBuffer) -> None:
    """append 후 extract_speech가 올바른 numpy 배열을 반환한다."""
    chunk = np.ones(512, dtype=np.float32)
    buf.append(chunk)
    result = buf.extract_speech()
    assert len(result) == 512
    assert np.allclose(result, 1.0)


def test_extract_is_nondestructive(buf: AudioBuffer) -> None:
    """extract_speech는 버퍼를 비우지 않는다."""
    buf.append(np.ones(512, dtype=np.float32))
    buf.extract_speech()
    assert not buf.is_empty()


def test_consume_clears_buffer(buf: AudioBuffer) -> None:
    """consume_speech 후 버퍼가 비어있다."""
    buf.append(np.ones(512, dtype=np.float32))
    _ = buf.consume_speech()
    assert buf.is_empty()


def test_empty_buffer_extract(buf: AudioBuffer) -> None:
    """빈 버퍼에서 extract_speech는 빈 배열을 반환한다."""
    result = buf.extract_speech()
    assert len(result) == 0


def test_duration_sec_accuracy(buf: AudioBuffer) -> None:
    """1초치 샘플 추가 후 duration_sec가 1.0에 가깝다."""
    buf.append(np.zeros(16000, dtype=np.float32))
    assert abs(buf.duration_sec() - 1.0) < 0.001


def test_hardcap_trims_oldest(buf: AudioBuffer) -> None:
    """max_duration_sec 초과 시 가장 오래된 샘플이 제거된다."""
    # 0.6초 + 0.6초 = 1.2초 (캡 1.0초 초과)
    buf.append(np.full(9600, 1.0, dtype=np.float32))
    buf.append(np.full(9600, 2.0, dtype=np.float32))
    # 캡 이후 남은 데이터는 1.0초치 (16000샘플) 이하
    assert buf.duration_sec() <= 1.0 + 0.001


def test_clear_resets_all(buf: AudioBuffer) -> None:
    """clear 후 is_empty=True이고 duration=0이다."""
    buf.append(np.ones(512, dtype=np.float32))
    buf.clear()
    assert buf.is_empty()
    assert buf.duration_sec() == 0.0
