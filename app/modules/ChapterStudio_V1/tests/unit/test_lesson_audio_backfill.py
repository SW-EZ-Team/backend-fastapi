from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

import pytest

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.app import lesson_audio_backfill as backfill
from app.modules.ChapterStudio_V1.pipeline.tts_routing import TutorVoiceProfile


class FakeConnectionManager:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self.conn

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.voice_rows: list[dict[str, object]] = [_voice_row(0), _voice_row(1)]

    async def fetch(self, query: str, *args: object) -> Sequence[Mapping[str, object]]:
        if "information_schema.columns" in query:
            return _columns(str(args[0]), str(args[1]))
        return self.voice_rows

    async def execute(self, query: str, *args: object) -> object:
        self.executed.append((query, args))
        return "UPDATE 1"


@pytest.mark.asyncio
async def test_backfill_lesson_audio_updates_audio_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection()
    profiles: list[TutorVoiceProfile] = []

    async def fake_load(db_conn: object, lesson_id: str) -> GenerationContext:
        return _context(lesson_id)

    async def fake_synthesize(
        scripts: list[dict[str, object]],
        *,
        tutor_profile: TutorVoiceProfile,
    ) -> list[dict[str, object]]:
        profiles.append(tutor_profile)
        idx = int(scripts[0]["slide_idx"])
        return [{"slide_idx": idx, "audio_url": f"mock://audio/{idx}", "duration_hint_sec": 2.5 + idx}]

    monkeypatch.setattr(backfill, "get_connection", lambda: FakeConnectionManager(conn))
    monkeypatch.setattr(backfill, "load_generation_context", fake_load)
    monkeypatch.setattr(backfill, "synthesize_voice_audio", fake_synthesize)

    result = await backfill.backfill_lesson_audio("lesson-1", tutor_id="tut_00000000000000PRESET_CAT01")

    queries = [query for query, _args in conn.executed]
    assert result == {"lesson_id": "lesson-1", "updated": 2, "failed": 0}
    assert len(profiles) == 2
    assert profiles[0].tutor_id == "tut_00000000000000PRESET_CAT01"
    assert any("UPDATE chapter_studio.voice_script" in query for query in queries)
    assert any("UPDATE chapter_studio.slide" in query for query in queries)
    assert any("UPDATE public.slide" in query for query in queries)
    assert conn.executed[0][1] == ("lesson-1", 0, "mock://audio/0", 2.5)


@pytest.mark.asyncio
async def test_backfill_lesson_audio_keeps_other_slides_when_one_tts_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection()
    profiles: list[TutorVoiceProfile] = []

    async def fake_load(db_conn: object, lesson_id: str) -> GenerationContext:
        return _context(lesson_id)

    async def fake_synthesize(
        scripts: list[dict[str, object]],
        *,
        tutor_profile: TutorVoiceProfile,
    ) -> list[dict[str, object]]:
        profiles.append(tutor_profile)
        idx = int(scripts[0]["slide_idx"])
        if idx == 1:
            raise RuntimeError("tts-disabled")
        return [{"slide_idx": idx, "audio_url": f"mock://audio/{idx}", "duration_hint_sec": 2.5}]

    monkeypatch.setattr(backfill, "get_connection", lambda: FakeConnectionManager(conn))
    monkeypatch.setattr(backfill, "load_generation_context", fake_load)
    monkeypatch.setattr(backfill, "synthesize_voice_audio", fake_synthesize)

    result = await backfill.backfill_lesson_audio("lesson-1")

    assert result == {"lesson_id": "lesson-1", "updated": 1, "failed": 1}
    assert profiles[0].tutor_id == "tut_00000000000000PRESET_CAT01"
    assert any(args[1] == 0 for _query, args in conn.executed)
    assert not any(args[1] == 1 for _query, args in conn.executed)


@pytest.mark.asyncio
async def test_backfill_lesson_audio_uses_tts_synth_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection()
    conn.voice_rows = [_voice_row(0), _voice_row(1), _voice_row(2)]
    active = 0
    max_active = 0
    warmup_calls = 0

    async def fake_load(db_conn: object, lesson_id: str) -> GenerationContext:
        return _context(lesson_id)

    async def fake_warmup(profile: TutorVoiceProfile) -> None:
        nonlocal warmup_calls
        warmup_calls += 1

    async def fake_synthesize(
        scripts: list[dict[str, object]],
        *,
        tutor_profile: TutorVoiceProfile,
    ) -> list[dict[str, object]]:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        idx = int(scripts[0]["slide_idx"])
        return [{"slide_idx": idx, "audio_url": f"mock://audio/{idx}", "duration_hint_sec": 2.5}]

    monkeypatch.setenv("TTS_SYNTH_CONCURRENCY", "2")
    monkeypatch.setattr(backfill, "get_connection", lambda: FakeConnectionManager(conn))
    monkeypatch.setattr(backfill, "load_generation_context", fake_load)
    monkeypatch.setattr(backfill, "warmup_tutor_voice_audio", fake_warmup)
    monkeypatch.setattr(backfill, "synthesize_voice_audio", fake_synthesize)

    result = await backfill.backfill_lesson_audio("lesson-1")

    assert result == {"lesson_id": "lesson-1", "updated": 3, "failed": 0}
    assert warmup_calls == 1
    assert max_active == 2


@pytest.mark.asyncio
async def test_backfill_lesson_audio_warms_up_before_bulk_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection()
    conn.voice_rows = [_voice_row(0), _voice_row(1), _voice_row(2)]
    events: list[str] = []

    async def fake_load(db_conn: object, lesson_id: str) -> GenerationContext:
        return _context(lesson_id)

    async def fake_warmup(profile: TutorVoiceProfile) -> None:
        events.append("warmup")

    async def fake_synthesize(
        scripts: list[dict[str, object]],
        *,
        tutor_profile: TutorVoiceProfile,
    ) -> list[dict[str, object]]:
        idx = int(scripts[0]["slide_idx"])
        events.append(f"synth-{idx}")
        return [{"slide_idx": idx, "audio_url": f"mock://audio/{idx}", "duration_hint_sec": 2.5}]

    monkeypatch.delenv("TTS_WARMUP_ENABLED", raising=False)
    monkeypatch.setattr(backfill, "get_connection", lambda: FakeConnectionManager(conn))
    monkeypatch.setattr(backfill, "load_generation_context", fake_load)
    monkeypatch.setattr(backfill, "warmup_tutor_voice_audio", fake_warmup)
    monkeypatch.setattr(backfill, "synthesize_voice_audio", fake_synthesize)

    result = await backfill.backfill_lesson_audio("lesson-1")

    assert result == {"lesson_id": "lesson-1", "updated": 3, "failed": 0}
    assert events[0] == "warmup"
    assert events.count("warmup") == 1
    assert {event for event in events[1:] if event.startswith("synth-")} == {
        "synth-0",
        "synth-1",
        "synth-2",
    }


@pytest.mark.asyncio
async def test_backfill_lesson_audio_skips_warmup_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection()
    conn.voice_rows = [_voice_row(0), _voice_row(1), _voice_row(2)]
    warmup_calls = 0

    async def fake_load(db_conn: object, lesson_id: str) -> GenerationContext:
        return _context(lesson_id)

    async def fake_warmup(profile: TutorVoiceProfile) -> None:
        nonlocal warmup_calls
        warmup_calls += 1

    async def fake_synthesize(
        scripts: list[dict[str, object]],
        *,
        tutor_profile: TutorVoiceProfile,
    ) -> list[dict[str, object]]:
        idx = int(scripts[0]["slide_idx"])
        return [{"slide_idx": idx, "audio_url": f"mock://audio/{idx}", "duration_hint_sec": 2.5}]

    monkeypatch.setenv("TTS_WARMUP_ENABLED", "false")
    monkeypatch.setattr(backfill, "get_connection", lambda: FakeConnectionManager(conn))
    monkeypatch.setattr(backfill, "load_generation_context", fake_load)
    monkeypatch.setattr(backfill, "warmup_tutor_voice_audio", fake_warmup)
    monkeypatch.setattr(backfill, "synthesize_voice_audio", fake_synthesize)

    result = await backfill.backfill_lesson_audio("lesson-1")

    assert result == {"lesson_id": "lesson-1", "updated": 3, "failed": 0}
    assert warmup_calls == 0


def _voice_row(slide_idx: int) -> dict[str, object]:
    return {"slide_idx": slide_idx, "script_text": f"{slide_idx}번 슬라이드 대본입니다."}


def _columns(schema: str, table: str) -> list[dict[str, object]]:
    values = {
        ("chapter_studio", "slide"): {"lesson_id", "chapter_id", "slide_idx", "audio_url", "duration_hint_sec"},
        ("public", "slide"): {"chapter_id", "slide_idx", "audio_url", "duration_sec"},
    }.get((schema, table), set())
    return [{"column_name": value} for value in values]


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
        use_formal_speech=False,
        tutor_tagline="친근한 말투",
        tutor_id="tut_00000000000000PRESET_CAT01",
    )
