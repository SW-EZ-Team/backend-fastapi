"""퀴즈 정답 위치 균등화 패스를 payload 단계에 적용한다."""
from __future__ import annotations

from app.modules.ChapterStudio_V1.common.config import quiz_balance_enabled
from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState
from app.modules.ChapterStudio_V1.postprocess.quiz_balance import balance_quiz_answers


def apply_quiz_balance_payload(
    payload: GeneratedLessonPayload,
    state: ChapterStudioState,
) -> GeneratedLessonPayload:
    """토글이 켜져 있으면 퀴즈 보기 순서를 결정적으로 재배치한다."""
    if not quiz_balance_enabled():
        return payload
    quizzes = balance_quiz_answers(payload.quizzes, seed_key=quiz_balance_seed_key(state))
    return payload.model_copy(update={"quizzes": quizzes})


def quiz_balance_seed_key(state: ChapterStudioState) -> str:
    """강의 식별자 후보를 이용해 보기 셔플 seed를 고정한다."""
    for key in ("lesson_id", "chapter_id", "chapter_title", "topic", "chapter_brief"):
        value = state.get(key)
        if isinstance(value, str) and value != "":
            return value
    return "chapterstudio"


__all__ = ["apply_quiz_balance_payload", "quiz_balance_seed_key"]
