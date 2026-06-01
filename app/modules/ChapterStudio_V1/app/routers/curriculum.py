"""커리큘럼 생성 API 라우터 — Spring CourseService가 호출하는 경로.

Spring POST /tutoring 처리 중 fire-and-forget 으로 호출되며(응답 본문 무시),
즉시 202를 반환하고 실제 생성·저장은 백그라운드에서 수행한다.
이후 Spring이 GET /tutoring/{id}/curriculum 으로 폴링해 결과를 조회한다.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.modules.ChapterStudio_V1.app.curriculum_generate import generate_and_store_curriculum

router = APIRouter(prefix="/api/curriculum", tags=["curriculum"])


class CurriculumGenerateRequest(BaseModel):
    """Spring CourseService.requestCurriculumGeneration 이 보내는 바디."""

    courseId: str = Field(min_length=1)
    subject: str = ""
    lessonCount: int = Field(default=10, ge=1, le=30)
    sourceType: str = "topic"


@router.post("/generate", status_code=202)
async def generate_curriculum(
    req: CurriculumGenerateRequest, background_tasks: BackgroundTasks
) -> dict[str, object]:
    """커리큘럼 생성을 비동기로 시작하고 202를 즉시 반환한다."""
    background_tasks.add_task(
        generate_and_store_curriculum,
        req.courseId,
        req.subject,
        req.lessonCount,
        req.sourceType,
    )
    return {"accepted": True, "courseId": req.courseId}
