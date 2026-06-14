from __future__ import annotations

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


# (삭제됨) test_curriculum_preview_codex_path_validates_json — CodexCLIConnector가
# 커밋 7abc300(codex CLI 커넥터 제거)에서 삭제되어 codex_cli 엔진 경로 테스트도 함께 제거함.


async def test_curriculum_preview_function_returns_contract(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_MOCK_PREVIEW", "true")
    preview = await build_curriculum_preview(
        CurriculumPreviewRequest(topic="통계 추론", title="통계 과외", lesson_count=10, engine="mock")
    )

    assert preview.status == "CURRICULUM_READY"
    assert len(preview.lessons) == 10
