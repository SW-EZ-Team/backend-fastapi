from __future__ import annotations

import os
from pathlib import Path

from pydantic import ValidationError

from app.modules.ChapterStudio_V1.ai_connectors.registry import get_text_connector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.app.curriculum_preview_types import (
    CurriculumLesson,
    CurriculumPreview,
    CurriculumPreviewRequest,
    SourceAnalysis,
)
from app.modules.ChapterStudio_V1.app.curriculum_stages import STAGES as _STAGES
from app.modules.ChapterStudio_V1.common.errors import ConversionError

_SCHEMA_PATH = Path(__file__).with_name("codex_curriculum_preview.schema.json")


async def build_curriculum_preview(req: CurriculumPreviewRequest) -> CurriculumPreview:
    """운영의 Opus Planner 자리를 mock 또는 활성 Gemini 커넥터로 미리 검증한다."""
    if req.engine == "gemini":
        return await _gemini_preview(req)
    return _mock_preview(req)


async def _gemini_preview(req: CurriculumPreviewRequest) -> CurriculumPreview:
    """활성 텍스트 커넥터(gemini_flash)로 커리큘럼 초안 JSON 을 생성한다."""
    response = await get_text_connector().generate(
        ChapterAIRequest(
            # gemini_flash thinking 토큰(~21000)이 예산을 먼저 잠식하므로 4200은 커리큘럼 초안 JSON이
            # 절단되기 쉽다. thinking 헤드룸을 확보해 24000으로 올린다(한도 65536 이내).
            system=_system_prompt(),
            user=_user_prompt(req),
            max_tokens=24000,
            temperature=0.25,
            extra={"output_schema_path": str(_SCHEMA_PATH)},
        )
    )
    try:
        return CurriculumPreview.model_validate_json(response.text)
    except ValidationError as exc:
        raise ConversionError("Gemini 커리큘럼 JSON을 검증하지 못했다.") from exc


def _mock_preview(req: CurriculumPreviewRequest) -> CurriculumPreview:
    if not _allow_mock_preview():
        raise RuntimeError("mock curriculum preview는 ALLOW_MOCK_PREVIEW=true에서만 허용된다.")
    lessons = [_lesson(req, index) for index in range(req.lesson_count)]
    total = sum(item.estimated_minutes for item in lessons)
    return CurriculumPreview(
        tutoring_id="demo-tutoring-preview",
        title=req.title,
        estimated_total_minutes=total,
        lessons=lessons,
        source_analysis=SourceAnalysis(
            detected_topics=[req.topic, req.subject, "핵심 개념", "적용 훈련"],
            difficulty_assessment=f"{req.difficulty} 기준으로 {req.lesson_count}강 초안 생성",
            recommended_prerequisites=["기본 용어", "대표 사례 1개", "질문 기록 습관"],
        ),
    )


def _allow_mock_preview() -> bool:
    """운영 경로에서 mock preview가 실수로 실행되지 않게 환경변수로 잠근다."""
    return os.getenv("ALLOW_MOCK_PREVIEW", "").lower() in {"1", "true", "yes"}


def _lesson(req: CurriculumPreviewRequest, index: int) -> CurriculumLesson:
    stage = _STAGES[index]
    prerequisite = None if index == 0 else f"{index}강 핵심 요약"
    return CurriculumLesson(
        order=index + 1,
        title=f"{req.topic} · {stage}",
        description=f"{stage} 단계에서 {req.topic}을 과외식으로 설명하고 바로 확인한다.",
        slide_count=10 + (index % 6),
        estimated_minutes=24 + (index % 5) * 4,
        key_topics=[stage, "배경 철학", "대표 예시", "자가 점검"],
        prerequisite=prerequisite,
    )


def _system_prompt() -> str:
    return (
        "너는 ChapterStudio_V1의 커리큘럼 Planner 미리보기다. "
        "운영에서는 Claude Opus 4.6이 맡는 역할이며, 지금은 활성 Gemini 커넥터로 초안을 만든다. "
        "커리큘럼은 10~15강, 각 강의는 10~15개 슬라이드로 생성될 수 있게 설계한다."
    )


def _user_prompt(req: CurriculumPreviewRequest) -> str:
    return (
        f"제목: {req.title}\n주제: {req.topic}\n과목: {req.subject}\n"
        f"입력 유형: {req.source_type}\n난이도: {req.difficulty}\n"
        f"희망 강의 수: {req.lesson_count}\n튜터: {req.teacher}\n\n"
        "CourseDetail 화면에 보여줄 커리큘럼 초안을 JSON으로만 출력한다. "
        "각 강의는 학습자가 왜 이 순서로 배우는지 이해할 수 있게 제목과 설명을 구체화한다. "
        "title/status/confirmed/estimated_total_minutes/lessons/source_analysis/tutoring_id 키를 모두 포함한다."
    )
