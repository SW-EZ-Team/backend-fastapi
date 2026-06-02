from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.app import lessons_generate
from app.modules.ChapterStudio_V1.app.routers import lessons as lessons_router


class FakeConnectionManager:
    def __init__(self, conn: object | None = None) -> None:
        self.conn = conn or object()

    async def __aenter__(self) -> object:
        return self.conn

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


@pytest.mark.asyncio
async def test_generate_loaded_context_triggers_audio_backfill_after_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    context = _context("lesson-1")

    async def fake_generate(input_payload: object) -> dict[str, object]:
        events.append("generate")
        return {"voice_scripts": []}

    def fake_response(state: object, chapter_id: str) -> object:
        events.append("response")
        return type("Response", (), {"slides": [object(), object()]})()

    async def fake_persist(conn: object, ctx: GenerationContext, chapter_id: str, state: object) -> None:
        events.append("persist")

    async def fake_mark(conn: object, lesson_id: str, slide_count: int) -> None:
        events.append("mark")

    async def fake_backfill(ctx: GenerationContext) -> None:
        events.append("backfill")

    monkeypatch.setattr(lessons_generate, "generate_chapter_state", fake_generate)
    monkeypatch.setattr(lessons_generate, "state_to_response", fake_response)
    monkeypatch.setattr(lessons_generate, "persist_chapter_state", fake_persist)
    monkeypatch.setattr(lessons_generate, "_mark_public_chapter_available", fake_mark)
    monkeypatch.setattr(lessons_generate, "_backfill_audio_when_needed", fake_backfill)
    monkeypatch.setattr(lessons_generate, "get_connection", lambda: FakeConnectionManager())

    result = await lessons_generate._generate_loaded_context(context)

    assert result is True
    assert events == ["generate", "response", "persist", "mark", "backfill"]


def test_audio_backfill_route_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_backfill(lesson_id: str, tutor_id: str | None = None) -> dict[str, object]:
        captured["lesson_id"] = lesson_id
        captured["tutor_id"] = tutor_id
        return {"lesson_id": lesson_id, "updated": 1, "failed": 0}

    monkeypatch.setattr(lessons_router, "backfill_lesson_audio", fake_backfill)
    app = FastAPI()
    app.include_router(lessons_router.router)

    response = TestClient(app).post(
        "/api/lessons/lesson-1/audio-backfill",
        json={"tutorId": "tut_00000000000000PRESET_CAT01"},
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": True, "lessonId": "lesson-1"}
    assert captured == {
        "lesson_id": "lesson-1",
        "tutor_id": "tut_00000000000000PRESET_CAT01",
    }


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
        tutor_id="tut_00000000000000PRESET_CAT01",
    )
