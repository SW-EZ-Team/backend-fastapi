"""tutor_preview 라우터 단위 테스트 — 텍스트+음성(audioUrl) 응답 계약을 검증한다."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.modules.ChapterStudio_V1.app.routers import tutor_preview
from app.modules.ChapterStudio_V1.pipeline.tts_routing import TutorVoiceProfile


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(tutor_preview.router)
    return TestClient(app)


def _patch_text(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_generate(**kwargs: object) -> tuple[str, list[str]]:
        return "미분은 순간 변화율이에요.", ["존댓말", "이모지 미사용"]

    monkeypatch.setattr(tutor_preview, "generate_tutor_preview", fake_generate)


def test_preview_returns_audio_url_on_tts_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """TTS 합성이 성공하면 audioUrl 이 채워지고 voiceSampleUrl 이 프로필로 전달된다."""
    _patch_text(monkeypatch)
    captured: dict[str, object] = {}

    async def fake_synthesize(records: list[dict[str, object]], *, tutor_profile: TutorVoiceProfile) -> list[dict[str, object]]:
        captured["profile"] = tutor_profile
        captured["script_text"] = records[0]["script_text"]
        return [{"slide_idx": 0, "audio_url": "http://localhost:9000/sw-ez-media/tts/p.wav"}]

    monkeypatch.setattr(tutor_preview, "synthesize_voice_audio", fake_synthesize)

    res = _client().post(
        "/api/tutors/tut_X/preview",
        json={
            "sampleQuestion": "미분이 뭐예요?",
            "useFormalSpeech": True,
            "voiceSampleUrl": "http://localhost:9000/sw-ez-media/voice-samples/ref.wav",
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["previewText"] == "미분은 순간 변화율이에요."
    assert body["audioUrl"] == "http://localhost:9000/sw-ez-media/tts/p.wav"
    profile = captured["profile"]
    assert isinstance(profile, TutorVoiceProfile)
    assert profile.voice_sample_url == "http://localhost:9000/sw-ez-media/voice-samples/ref.wav"
    assert profile.use_formal_speech is True
    # TTS 입력은 생성된 미리보기 멘트여야 한다 (학생 질문이 아님)
    assert captured["script_text"] == "미분은 순간 변화율이에요."


def test_preview_returns_null_audio_url_on_tts_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """TTS 합성 실패는 best-effort — 200 + audioUrl null 로 텍스트 미리보기를 지킨다."""
    _patch_text(monkeypatch)

    async def fake_synthesize(records: list[dict[str, object]], *, tutor_profile: TutorVoiceProfile) -> list[dict[str, object]]:
        raise RuntimeError("TTS 엔진 다운")

    monkeypatch.setattr(tutor_preview, "synthesize_voice_audio", fake_synthesize)

    res = _client().post("/api/tutors/tut_X/preview", json={"sampleQuestion": "미분이 뭐예요?"})

    assert res.status_code == 200
    body = res.json()
    assert body["previewText"] == "미분은 순간 변화율이에요."
    assert body["audioUrl"] is None


def test_preview_without_voice_sample_url_is_backward_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    """voiceSampleUrl 미포함(구버전 Spring) 바디도 그대로 동작한다 — 기본 TTS 경로 프로필."""
    _patch_text(monkeypatch)
    captured: dict[str, object] = {}

    async def fake_synthesize(records: list[dict[str, object]], *, tutor_profile: TutorVoiceProfile) -> list[dict[str, object]]:
        captured["profile"] = tutor_profile
        return [{"slide_idx": 0, "audio_url": "/media/tts/p.wav"}]

    monkeypatch.setattr(tutor_preview, "synthesize_voice_audio", fake_synthesize)

    res = _client().post("/api/tutors/tut_X/preview", json={"sampleQuestion": "적분은요?"})

    assert res.status_code == 200
    assert res.json()["audioUrl"] == "/media/tts/p.wav"
    profile = captured["profile"]
    assert isinstance(profile, TutorVoiceProfile)
    assert profile.voice_sample_url == ""
    # useFormalSpeech 미지정 시 존댓말 기본값으로 합성한다
    assert profile.use_formal_speech is True
