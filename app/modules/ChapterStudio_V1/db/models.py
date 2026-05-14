from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, MetaData, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

metadata = MetaData(schema="chapter_studio")


class Base(DeclarativeBase):
    metadata = metadata


class Slide(Base):
    """SlideGenerator 출력 슬라이드 참조 모델이다."""

    __tablename__ = "slide"
    __table_args__ = (Index("idx_chapter_studio_slide_chapter", "chapter_id", "index"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String, nullable=False)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    css: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceScript(Base):
    """VoiceScriptWriter 출력 음성 대본 참조 모델이다."""

    __tablename__ = "voice_script"
    __table_args__ = (Index("idx_chapter_studio_voice_script_chapter", "chapter_id", "slide_index"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String, nullable=False)
    slide_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    duration_hint_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Quiz(Base):
    """QuizMaker 출력 퀴즈 참조 모델이다."""

    __tablename__ = "quiz"
    __table_args__ = (Index("idx_chapter_studio_quiz_chapter", "chapter_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    choices: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    answer_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Note(Base):
    """NoteSummarizer 출력 핵심 노트 참조 모델이다."""

    __tablename__ = "note"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Assignment(Base):
    """AssignmentSeedMaker 출력 과제 시드 참조 모델이다."""

    __tablename__ = "assignment"
    __table_args__ = (Index("idx_chapter_studio_assignment_chapter", "chapter_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    criteria: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    expected_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChapterAudio(Base):
    """TTS V1 큐 워커 완료 결과 참조 모델이다."""

    __tablename__ = "chapter_audio"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    merged_audio_url: Mapped[str] = mapped_column(String, nullable=False)
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceScriptQueue(Base):
    """TTS V1 비동기 처리 큐 참조 모델이다."""

    __tablename__ = "voice_script_queue"
    __table_args__ = (Index("idx_chapter_studio_queue_status", "status", "enqueued_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    voice_script_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("chapter_studio.voice_script.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
