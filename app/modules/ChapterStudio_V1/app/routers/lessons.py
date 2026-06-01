"""강의 생성 API 라우터 — Spring CourseService.confirmCurriculum 이 호출하는 경로.

Spring은 커리큘럼 확정 시 {courseId} 만 보내고(fire-and-forget), 즉시 202를 받는다.
실제 강의 생성(전 chapter 순회)은 백그라운드에서 수행하고, Spring은 이후
GET /tutoring/{id}/lessons/{chapterId}/slides 등으로 폴링한다.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.modules.ChapterStudio_V1.app.lessons_generate import generate_lesson_for_chapter, generate_lessons_for_course

router = APIRouter(prefix="/api/lessons", tags=["lessons"])


class LessonsGenerateRequest(BaseModel):
    """Spring CourseService.requestLessonGeneration 이 보내는 바디."""

    courseId: str = Field(min_length=1)


class LessonGenerateOneRequest(BaseModel):
    """단건 progressive 강의 생성 요청 바디."""

    courseId: str = Field(min_length=1)
    lessonId: str = Field(min_length=1)
    audienceLevel: str | None = Field(default=None, max_length=80)
    learningGoal: str | None = Field(default=None, max_length=160)
    tone: int | None = Field(default=None, ge=0, le=100)
    pace: int | None = Field(default=None, ge=0, le=100)
    tutorDepth: int | None = Field(default=None, ge=0, le=100)
    socratic: int | None = Field(default=None, ge=0, le=100)


@router.post("/generate", status_code=202)
async def generate_lessons(
    req: LessonsGenerateRequest, background_tasks: BackgroundTasks
) -> dict[str, object]:
    """강의 생성을 비동기로 시작하고 202를 즉시 반환한다."""
    background_tasks.add_task(generate_lessons_for_course, req.courseId)
    return {"accepted": True, "courseId": req.courseId}


@router.post("/generate-one", status_code=202)
async def generate_one_lesson(
    req: LessonGenerateOneRequest, background_tasks: BackgroundTasks
) -> dict[str, object]:
    """강의 1개를 비동기로 생성하고 202를 즉시 반환한다."""
    background_tasks.add_task(
        generate_lesson_for_chapter,
        req.courseId,
        req.lessonId,
        audience_level=req.audienceLevel,
        learning_goal=req.learningGoal,
        tone=req.tone,
        pace=req.pace,
        tutor_depth=req.tutorDepth,
        socratic=req.socratic,
    )
    return {"accepted": True, "courseId": req.courseId, "lessonId": req.lessonId}
