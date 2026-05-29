"""ASR_V1 통합 테스트 — 스프링이 보내는 실제 HTTP 요청으로 검증한다.

mock, MagicMock, @patch, monkeypatch 절대 금지.
POST /api/asr-v1/offline (파일 업로드) 엔드포인트를 검증한다.
WebSocket 엔드포인트는 별도 WebSocket 클라이언트가 필요하므로 REST만 대상으로 한다.
"""
from __future__ import annotations

import importlib

import pytest
from httpx import AsyncClient

# mlx_qwen3_asr 패키지 설치 여부 — 미설치 시 실제 ASR 파이프라인이 ModelLoadError 발생
_has_mlx_qwen3_asr = importlib.util.find_spec("mlx_qwen3_asr") is not None


# ─── 정상 오디오 파일 업로드 ─────────────────────────────────────────────────

@pytest.mark.anyio
@pytest.mark.skipif(not _has_mlx_qwen3_asr, reason="mlx_qwen3_asr 미설치 — ASR 엔드포인트가 500 대신 예외 발생")
async def test_offline_transcribe_basic(client: AsyncClient) -> None:
    """스프링이 오디오 파일을 전사 요청할 때 스키마 레이어를 통과한다.

    실제 ASR 모델 없이는 파이프라인에서 오류가 나지만 스키마는 통과해야 한다.
    """
    # WAV 파일 헤더 (RIFF/WAV 최소 구조) — 실제 오디오 데이터 없는 더미
    # 44바이트 WAV 헤더: RIFF 청크 + fmt 청크 최소 구조
    wav_header = (
        b"RIFF"
        + (36).to_bytes(4, "little")  # 파일 크기 - 8
        + b"WAVE"
        + b"fmt "
        + (16).to_bytes(4, "little")  # fmt 청크 크기
        + (1).to_bytes(2, "little")   # PCM 포맷
        + (1).to_bytes(2, "little")   # 모노
        + (16000).to_bytes(4, "little")  # 16kHz 샘플레이트
        + (32000).to_bytes(4, "little")  # 바이트레이트
        + (2).to_bytes(2, "little")   # 블록 정렬
        + (16).to_bytes(2, "little")  # 비트 깊이
        + b"data"
        + (0).to_bytes(4, "little")   # 데이터 없음
    )

    files = {
        "audio": ("lecture_recording.wav", wav_header, "audio/wav"),
    }
    params = {
        "language": "ko",
        "model": "mlx-qwen3-asr",
    }

    response = await client.post(
        "/api/asr-v1/offline", files=files, params=params
    )
    # 실제 모델 없이는 500이 발생할 수 있으나 스키마는 통과해야 한다
    assert response.status_code in {200, 500}
    assert response.status_code != 422


@pytest.mark.anyio
@pytest.mark.skipif(not _has_mlx_qwen3_asr, reason="mlx_qwen3_asr 미설치 — ASR 엔드포인트가 500 대신 예외 발생")
async def test_offline_transcribe_without_model_param(
    client: AsyncClient,
) -> None:
    """model 파라미터 없이 요청하면 기본 모델이 사용된다 (422 아님)."""
    wav_header = b"RIFF" + b"\x00" * 36  # 최소 더미 WAV
    files = {
        "audio": ("강의녹음.wav", wav_header, "audio/wav"),
    }
    params = {"language": "ko"}

    response = await client.post(
        "/api/asr-v1/offline", files=files, params=params
    )
    assert response.status_code in {200, 500}
    assert response.status_code != 422


@pytest.mark.anyio
@pytest.mark.skipif(not _has_mlx_qwen3_asr, reason="mlx_qwen3_asr 미설치 — ASR 엔드포인트가 500 대신 예외 발생")
async def test_offline_transcribe_english_audio(client: AsyncClient) -> None:
    """영어 오디오 전사 요청이 스키마를 통과한다."""
    dummy_audio = b"RIFF" + b"\x00" * 36
    files = {
        "audio": ("english_lecture.wav", dummy_audio, "audio/wav"),
    }
    params = {"language": "en"}

    response = await client.post(
        "/api/asr-v1/offline", files=files, params=params
    )
    assert response.status_code in {200, 500}
    assert response.status_code != 422


# ─── 필수 필드 누락 ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_offline_transcribe_missing_audio_returns_422(
    client: AsyncClient,
) -> None:
    """audio 파일 없이 요청하면 422를 반환한다."""
    params = {"language": "ko"}
    response = await client.post("/api/asr-v1/offline", params=params)
    assert response.status_code == 422


# ─── 경계 케이스 ────────────────────────────────────────────────────────────

@pytest.mark.anyio
@pytest.mark.skipif(not _has_mlx_qwen3_asr, reason="mlx_qwen3_asr 미설치 — ASR 엔드포인트가 500 대신 예외 발생")
async def test_offline_transcribe_empty_audio_bytes(
    client: AsyncClient,
) -> None:
    """빈 바이트 오디오 파일도 스키마는 통과하지만 파이프라인에서 실패한다."""
    files = {
        "audio": ("empty.wav", b"", "audio/wav"),
    }
    params = {"language": "ko"}

    response = await client.post(
        "/api/asr-v1/offline", files=files, params=params
    )
    # 빈 파일은 파이프라인에서 오류 — 500이 예상되지만 422는 아니어야 한다
    assert response.status_code in {200, 500}
