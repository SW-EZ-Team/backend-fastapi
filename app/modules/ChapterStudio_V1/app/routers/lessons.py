"""강의 생성 API 라우터 — Spring CourseService.confirmCurriculum 이 호출하는 경로.

Spring은 커리큘럼 확정 시 {courseId} 만 보내고(fire-and-forget), 즉시 202를 받는다.
실제 강의 생성(전 chapter 순회)은 백그라운드에서 수행하고, Spring은 이후
GET /tutoring/{id}/lessons/{chapterId}/slides 등으로 폴링한다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.modules.ChapterStudio_V1.app.lesson_audio_backfill import backfill_lesson_audio
from app.modules.ChapterStudio_V1.app.lessons_generate import generate_lesson_for_chapter, generate_lessons_for_course

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lessons", tags=["lessons"])


async def _run_course_generation_logged(course_id: str) -> None:
    """course 전체 생성을 BackgroundTask로 돌리되, 미처리 예외를 풀 스택과 함께 남긴다.

    FastAPI BackgroundTask는 예외를 조용히 삼키므로, 여기서 감싸 로그에 남긴 뒤
    동작 보존을 위해 다시 전파한다(조용한 실패 가시화 목적).
    """
    try:
        await generate_lessons_for_course(course_id)
    except Exception:
        _LOG.exception("[lessons] background 강의 일괄 생성 미처리 예외 — courseId=%s", course_id)
        raise


async def _run_lesson_generation_logged(course_id: str, lesson_id: str, **kwargs: object) -> None:
    """단건 강의 생성을 BackgroundTask로 돌리되, 미처리 예외를 풀 스택과 함께 남긴다.

    BackgroundTask가 삼키는 예외를 먼저 로깅하고 다시 전파한다(동작 보존).
    """
    try:
        await generate_lesson_for_chapter(course_id, lesson_id, **kwargs)
    except Exception:
        _LOG.exception(
            "[lessons] background 강의 생성 미처리 예외 — courseId=%s lessonId=%s",
            course_id,
            lesson_id,
        )
        raise


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
    useFormalSpeech: bool | None = None
    useEmoji: bool | None = None
    tutorName: str | None = Field(default=None, max_length=80)
    tutorTagline: str | None = Field(default=None, max_length=160)
    isDefaultTutor: bool | None = None
    voiceSampleUrl: str | None = Field(default=None, max_length=1000)


class LessonAudioBackfillRequest(BaseModel):
    """저장된 강의 음성만 후처리로 채우는 요청 바디."""

    tutorId: str | None = Field(default=None, min_length=1, max_length=30)


@router.post("/generate", status_code=202)
async def generate_lessons(
    req: LessonsGenerateRequest, background_tasks: BackgroundTasks
) -> dict[str, object]:
    """강의 생성을 비동기로 시작하고 202를 즉시 반환한다."""
    background_tasks.add_task(_run_course_generation_logged, req.courseId)
    return {"accepted": True, "courseId": req.courseId}


@router.post("/generate-one", status_code=202)
async def generate_one_lesson(
    req: LessonGenerateOneRequest, background_tasks: BackgroundTasks
) -> dict[str, object]:
    """강의 1개를 비동기로 생성하고 202를 즉시 반환한다."""
    background_tasks.add_task(
        _run_lesson_generation_logged,
        req.courseId,
        req.lessonId,
        audience_level=req.audienceLevel,
        learning_goal=req.learningGoal,
        tone=req.tone,
        pace=req.pace,
        tutor_depth=req.tutorDepth,
        socratic=req.socratic,
        use_formal_speech=req.useFormalSpeech,
        use_emoji=req.useEmoji,
        tutor_name=req.tutorName,
        tutor_tagline=req.tutorTagline,
        is_default_tutor=req.isDefaultTutor,
        voice_sample_url=req.voiceSampleUrl,
    )
    return {"accepted": True, "courseId": req.courseId, "lessonId": req.lessonId}


@router.post("/{lessonId}/audio-backfill", status_code=202)
async def backfill_lesson_audio_route(
    lessonId: str,
    background_tasks: BackgroundTasks,
    req: LessonAudioBackfillRequest | None = None,
) -> dict[str, object]:
    """강의 재생성 없이 저장된 음성대본의 오디오 URL 생성을 예약한다."""
    tutor_id = req.tutorId if req is not None else None
    background_tasks.add_task(backfill_lesson_audio, lessonId, tutor_id)
    return {"accepted": True, "lessonId": lessonId}
