"""TTS_V2 통합 테스트 — 스프링이 보내는 실제 JSON 페이로드로 검증한다.

mock, MagicMock, @patch, monkeypatch 절대 금지.
POST /api/tts-v2 (텍스트 입력) 와 GET /api/tts-v2/voices 를 검증한다.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


# ─── 음성 프로필 목록 (외부 의존 없음) ───────────────────────────────────────

@pytest.mark.anyio
async def test_list_voices_returns_profiles(client: AsyncClient) -> None:
    """등록된 고정 튜터 음성 프로필 목록이 반환된다."""
    response = await client.get("/api/tts-v2/voices")
    assert response.status_code == 200
    data = response.json()
    # profiles 키가 존재하고 리스트여야 한다
    assert "profiles" in data
    assert isinstance(data["profiles"], list)


# ─── 정상 텍스트 요청 ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_synthesize_text_basic_schema(client: AsyncClient) -> None:
    """스프링이 보내는 기본 TTS 요청이 스키마 검증을 통과한다.

    실제 TTS 모델이 없어도 라우터·스키마 레이어는 검증 가능하다.
    """
    payload: dict = {
        "text": (
            "안녕하세요, 오늘 강의에서는 파이썬 리스트 컴프리헨션에 대해 알아보겠습니다. "
            "리스트 컴프리헨션은 기존 for 루프를 한 줄로 간결하게 작성할 수 있는 "
            "파이썬의 강력한 문법입니다."
        ),
        "voice_profile_id": None,
        "ref_audio_base64": None,
        "ref_text": None,
        "language": "ko",
        "speed": 1.0,
        "skip_planner": True,
        "skip_postfx": False,
        "qc_engine": "whisperx",
    }

    response = await client.post("/api/tts-v2", json=payload)
    # 실제 모델 없이 파이프라인이 실패할 수 있으나 스키마는 통과해야 한다
    assert response.status_code in {200, 400, 500}
    # 422는 스키마 오류이므로 허용하지 않는다
    assert response.status_code != 422


@pytest.mark.anyio
async def test_synthesize_with_speed_variation(client: AsyncClient) -> None:
    """다양한 재생 속도 값을 가진 요청이 스키마를 통과한다."""
    for speed in [0.5, 0.8, 1.0, 1.5, 2.0]:
        payload: dict = {
            "text": "속도 테스트를 위한 짧은 강의 텍스트입니다.",
            "language": "ko",
            "speed": speed,
            "skip_planner": True,
        }
        response = await client.post("/api/tts-v2", json=payload)
        # 422(스키마 오류)만 명시적으로 거부
        assert response.status_code != 422, f"speed={speed}에서 스키마 오류 발생"


# ─── 유효성 검사 오류 ──────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_empty_text_returns_422(client: AsyncClient) -> None:
    """빈 text 필드는 422 검증 오류를 반환한다."""
    payload: dict = {
        "text": "",
        "language": "ko",
    }
    response = await client.post("/api/tts-v2", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_speed_out_of_range_returns_422(client: AsyncClient) -> None:
    """허용 범위(0.5~2.0)를 벗어난 speed 값은 422를 반환한다."""
    payload: dict = {
        "text": "범위 초과 속도 테스트",
        "speed": 3.5,  # 최대값 2.0 초과
    }
    response = await client.post("/api/tts-v2", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_speed_below_minimum_returns_422(client: AsyncClient) -> None:
    """최솟값(0.5) 미만 speed는 422를 반환한다."""
    payload: dict = {
        "text": "최솟값 미만 속도 테스트",
        "speed": 0.1,
    }
    response = await client.post("/api/tts-v2", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_partial_ref_audio_without_ref_text_returns_400(
    client: AsyncClient,
) -> None:
    """ref_audio_base64만 있고 ref_text가 없으면 400을 반환한다."""
    payload: dict = {
        "text": "레퍼런스 오디오 검증 테스트",
        "ref_audio_base64": "dGVzdA==",  # "test"의 base64 인코딩 (유효한 base64)
        "ref_text": None,  # ref_text 누락
        "language": "ko",
    }
    response = await client.post("/api/tts-v2", json=payload)
    # 라우터에서 400을 반환해야 한다
    assert response.status_code == 400


@pytest.mark.anyio
async def test_missing_text_field_returns_422(client: AsyncClient) -> None:
    """text 필드 자체가 누락되면 422를 반환한다."""
    payload: dict = {
        "language": "ko",
        "speed": 1.0,
    }
    response = await client.post("/api/tts-v2", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_invalid_base64_ref_audio_returns_400(client: AsyncClient) -> None:
    """유효하지 않은 base64 ref_audio_base64는 400을 반환한다."""
    payload: dict = {
        "text": "잘못된 base64 레퍼런스 테스트",
        "ref_audio_base64": "!!!not-valid-base64!!!",
        "ref_text": "테스트 레퍼런스 텍스트",
        "language": "ko",
    }
    response = await client.post("/api/tts-v2", json=payload)
    assert response.status_code == 400
