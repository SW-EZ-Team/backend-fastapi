from __future__ import annotations

import json

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIResponse
from app.modules.ChapterStudio_V1.app.curriculum_preview import build_curriculum_preview
from app.modules.ChapterStudio_V1.app.curriculum_preview_types import CurriculumPreviewRequest


async def test_curriculum_preview_mock_matches_course_detail_contract(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_MOCK_PREVIEW", "true")
    preview = await build_curriculum_preview(
        CurriculumPreviewRequest(topic="통계 추론", title="통계 과외", lesson_count=10, engine="mock")
    )

    assert preview.status == "CURRICULUM_READY"
    assert preview.confirmed is False
    assert len(preview.lessons) == 10
    assert all(10 <= lesson.slide_count <= 15 for lesson in preview.lessons)


async def test_curriculum_preview_codex_path_validates_json(monkeypatch) -> None:
    class FakeCodex:
        async def generate(self, req):
            return ChapterAIResponse(
                text=_codex_json(),
                model="codex-test",
                input_tokens=1,
                output_tokens=1,
                finish_reason="stop",
            )

    monkeypatch.setattr("app.modules.ChapterStudio_V1.app.curriculum_preview.CodexCLIConnector", FakeCodex)
    preview = await build_curriculum_preview(
        CurriculumPreviewRequest(topic="생명과학", title="생명과학 과외", engine="codex_cli")
    )

    assert preview.title == "생명과학 과외"
    assert len(preview.lessons) == 10


async def test_curriculum_preview_function_returns_contract(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_MOCK_PREVIEW", "true")
    preview = await build_curriculum_preview(
        CurriculumPreviewRequest(topic="통계 추론", title="통계 과외", lesson_count=10, engine="mock")
    )

    assert preview.status == "CURRICULUM_READY"
    assert len(preview.lessons) == 10


def _codex_json() -> str:
    lessons = [
        {
            "order": index + 1,
            "title": f"생명과학 {index + 1}강",
            "description": "세포와 유전 개념을 순서대로 학습한다.",
            "slide_count": 10,
            "estimated_minutes": 25,
            "key_topics": ["관점", "용어", "예시"],
            "prerequisite": None if index == 0 else f"{index}강",
        }
        for index in range(10)
    ]
    return json.dumps(
        {
            "tutoring_id": "demo",
            "title": "생명과학 과외",
            "status": "CURRICULUM_READY",
            "confirmed": False,
            "estimated_total_minutes": 250,
            "lessons": lessons,
            "source_analysis": {
                "detected_topics": ["세포", "유전", "대사"],
                "difficulty_assessment": "표준",
                "recommended_prerequisites": ["기초 용어"],
            },
        },
        ensure_ascii=False,
    )
