from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.app import lessons_generate
from app.modules.ChapterStudio_V1.app.routers import lessons as lessons_router


class FakeConnectionManager:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


@pytest.mark.asyncio
async def test_generate_lesson_for_chapter_injects_aggregated_weak_points(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, GenerationContext] = {}

    async def fake_aggregate(conn: object, course_id: str, lesson_id: str) -> str:
        return "표본분포, p-value"

    async def fake_load(conn: object, lesson_id: str) -> GenerationContext:
        return _context(lesson_id)

    async def fake_generate(context: GenerationContext) -> bool:
        captured["context"] = context
        return True

    monkeypatch.setattr(lessons_generate, "get_connection", lambda: FakeConnectionManager())
    monkeypatch.setattr(lessons_generate, "aggregate_weak_points", fake_aggregate)
    monkeypatch.setattr(lessons_generate, "load_generation_context", fake_load)
    monkeypatch.setattr(lessons_generate, "_generate_loaded_context", fake_generate)

    result = await lessons_generate.generate_lesson_for_chapter(
        "course-1",
        "lesson-1",
        audience_level="통계 입문자",
        learning_goal="검정과 추정을 분리",
        tone=60,
        use_formal_speech=False,
        use_emoji=True,
        tutor_name="냥 튜터",
        tutor_tagline="친근한 말투 · 비유 잘 씀",
        is_default_tutor=True,
        voice_sample_url="https://cdn.local/cat.wav",
    )

    assert result is True
    assert captured["context"].weak_points == "표본분포, p-value"
    assert captured["context"].audience_level == "통계 입문자"
    assert captured["context"].learning_goal == "검정과 추정을 분리"
    assert captured["context"].tone == 60
    assert captured["context"].use_formal_speech is False
    assert captured["context"].use_emoji is True
    assert captured["context"].tutor_name == "냥 튜터"
    assert captured["context"].voice_sample_url == "https://cdn.local/cat.wav"


def test_generate_one_route_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_generate(course_id: str, lesson_id: str, **kwargs: object) -> bool:
        captured["course_id"] = course_id
        captured["lesson_id"] = lesson_id
        captured["kwargs"] = kwargs
        return True

    monkeypatch.setattr(lessons_router, "generate_lesson_for_chapter", fake_generate)
    app = FastAPI()
    app.include_router(lessons_router.router)

    response = TestClient(app).post(
        "/api/lessons/generate-one",
        json={
            "courseId": "course-1",
            "lessonId": "lesson-1",
            "audienceLevel": "입문자",
            "tutorDepth": 80,
            "useFormalSpeech": False,
            "useEmoji": True,
            "tutorName": "냥 튜터",
            "tutorTagline": "친근한 말투 · 비유 잘 씀",
            "isDefaultTutor": True,
            "voiceSampleUrl": "https://cdn.local/cat.wav",
        },
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": True, "courseId": "course-1", "lessonId": "lesson-1"}
    assert captured["course_id"] == "course-1"
    assert captured["lesson_id"] == "lesson-1"
    assert captured["kwargs"]["audience_level"] == "입문자"
    assert captured["kwargs"]["tutor_depth"] == 80
    assert captured["kwargs"]["use_formal_speech"] is False
    assert captured["kwargs"]["use_emoji"] is True
    assert captured["kwargs"]["tutor_name"] == "냥 튜터"
    assert captured["kwargs"]["voice_sample_url"] == "https://cdn.local/cat.wav"


def _context(lesson_id: str) -> GenerationContext:
    return GenerationContext(
        lesson_id=lesson_id,
        tutoring_id="course-1",
        user_id="user-1",
        curriculum_plan_id="plan-1",
        topic="통계 추론",
        source_mode="topic",
        chapter_title="통계 추론",
        chapter_brief="p-value와 신뢰구간",
        slide_count=10,
    )
