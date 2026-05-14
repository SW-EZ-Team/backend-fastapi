from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ChapterStudio_V1.app.reference_books.ocr_bridge import reference_context_from_ocr_result
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext


class ReferenceBookPreviewRequest(BaseModel):
    """수동 HTML 테스트에서 쓰는 참고도서 컨텍스트 미리보기 요청이다."""

    model_config = ConfigDict(strict=True)

    topic: str = Field(min_length=1, max_length=200)
    chapter_brief: str = Field(default="", max_length=400)
    learning_goal: str = Field(default="", max_length=160)
    weak_points: str = Field(default="", max_length=240)
    source_title: str = Field(default="사용자 참고도서", max_length=200)
    ocr_result: dict[str, object] = Field(default_factory=dict)


def build_reference_book_preview(req: ReferenceBookPreviewRequest) -> ReferenceBookContext:
    """OCR 결과와 강의 입력을 합쳐 참고도서 발췌 top-k를 반환한다."""
    return reference_context_from_ocr_result(
        req.ocr_result,
        [req.topic, req.chapter_brief, req.learning_goal, req.weak_points],
        source_title=req.source_title,
    )
