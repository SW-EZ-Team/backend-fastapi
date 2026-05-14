from __future__ import annotations

from app.modules.ChapterStudio_V1.app.demo_types import DemoStoragePreview
from app.modules.ChapterStudio_V1.app.study_templates import StudyTemplate
from app.modules.ChapterStudio_V1.app.template_visuals import visual_summary
from app.modules.ChapterStudio_V1.app.tutor_blueprints import TutorBlueprint


def quality_marks(template: StudyTemplate, blueprint: TutorBlueprint | None = None) -> list[str]:
    """사용자에게 보여줄 생성 품질 안전장치를 만든다."""
    marks = [
        f"템플릿: {template.label} · {template.intent}",
        visual_summary(template.key),
        "슬라이드 실습과 퀴즈 5문항을 별도 산출물로 분리",
        "핵심노트는 블록형으로 파싱해 한 덩어리 텍스트를 방지",
        "음성대본은 슬라이드별 TTS 합성 후 audio_url과 duration을 저장 가능",
        "후처리 순서: 렌더·sanitize 후 프론트 srcDoc 문서 HTML로 저장",
    ]
    if blueprint is not None:
        marks.insert(2, f"과외 관점: {blueprint.lens} · {blueprint.fast_route}")
    return marks


def storage_preview(
    slide_count: int, quiz_count: int, note_count: int, voice_count: int
) -> list[DemoStoragePreview]:
    """Phase 5 DBRouter가 받을 테이블별 저장 단위를 미리 보여준다."""
    return [
        {"table": "chapter_studio.slide", "rows": slide_count, "note": "iframeHtml srcDoc 문서 HTML"},
        {"table": "chapter_studio.quiz", "rows": quiz_count, "note": "객관식 5문항"},
        {"table": "chapter_studio.note", "rows": 1, "note": f"블록 {note_count}개를 1개 노트로 저장"},
        {"table": "chapter_studio.assignment", "rows": 1, "note": "과제 형식, 예상 시간, 본문과 rubric"},
        {"table": "chapter_studio.voice_script", "rows": voice_count, "note": "슬라이드별 대본 + TTS audio_url/duration"},
        {"table": "chapter_studio.voice_script_queue", "rows": voice_count, "note": "TTS 비동기 큐"},
        {"table": "chapter_studio.chapter_audio", "rows": 1, "note": "강의 전체 오디오 병합 결과"},
    ]
