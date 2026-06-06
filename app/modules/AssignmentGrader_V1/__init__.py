"""텍스트 과제 채점 모듈 — Gemini 기반 텍스트 답안 채점 후 Spring 콜백."""

from .router import router
from .grading_handler import handle_text_grading_request
from .schemas import GradeRequest, GradeResponse

__all__ = [
    "router",
    "handle_text_grading_request",
    "GradeRequest",
    "GradeResponse",
]
