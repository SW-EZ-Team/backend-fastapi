from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ChapterStudio_V1.app.frontend_contract import DepthLevel, SourceMode, TeacherId, depth_label, teacher_label
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext


class DemoGenerationInput(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    topic: str = Field(min_length=1, max_length=2000)
    source_mode: SourceMode = "topic"
    pdf_file_name: str = Field(default="", max_length=160)
    duration_days: int = Field(default=30, ge=1, le=365)
    depth: DepthLevel = "normal"
    teacher: TeacherId = "owl"
    tone: int = Field(default=50, ge=0, le=100)
    pace: int = Field(default=50, ge=0, le=100)
    tutor_depth: int = Field(default=50, ge=0, le=100)
    socratic: int = Field(default=70, ge=0, le=100)
    audience_level: str = Field(default="일반 학습자", max_length=80)
    learning_goal: str = Field(default="핵심 개념 이해와 실습", max_length=160)
    weak_points: str = Field(default="", max_length=240)
    chapter_title: str = Field(default="데모 챕터", max_length=120)
    chapter_brief: str = Field(default="", max_length=400)
    reference_book_context: ReferenceBookContext | None = None


def prompt_context(data: DemoGenerationInput) -> str:
    """프론트 입력값을 생성 모델이 읽는 짧은 맥락으로 압축한다."""
    source = _source_line(data)
    weak = data.weak_points or "없음"
    brief = data.chapter_brief or data.topic
    base = (
        f"입력모드: {source}\n"
        f"학습기간: {data.duration_days}일\n"
        f"난이도: {depth_label(data.depth)}\n"
        f"튜터: {teacher_label(data.teacher)}\n"
        f"튜터성향: 친근도 {data.tone}, 속도 {data.pace}, 깊이 {data.tutor_depth}, 질문우선 {data.socratic}\n"
        f"대상수준: {data.audience_level}\n"
        f"학습목표: {data.learning_goal}\n"
        f"취약점: {weak}\n"
        f"챕터제목: {data.chapter_title}\n"
        f"챕터요약: {brief}"
    )
    ref = _reference_line(data.reference_book_context)
    if ref:
        return f"{base}\n{ref}"
    return base


def _source_line(data: DemoGenerationInput) -> str:
    if data.source_mode == "pdf":
        name = data.pdf_file_name or "mock_uploaded.pdf"
        return f"PDF 업로드 · {name}"
    return "주제 입력"


def _reference_line(context: ReferenceBookContext | None) -> str:
    if context is None or not context.has_hits():
        return ""
    source = context.source_title or "사용자 참고도서"
    pages = ", ".join(f"p.{hit.page}" for hit in context.hits[:3])
    return f"참고도서: {source} · 관련 페이지 {pages}"
