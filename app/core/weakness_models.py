"""학습 약점 추적 공용 DB 모델이다.

소크라테스(QAResponder)와 과제 채점(AssignmentGrader) 두 경로에서 갱신된다.
ChapterStudio 전용이 아닌 공용 모듈이므로 public schema를 사용한다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# public schema 사용 — ChapterStudio의 chapter_studio 스키마와 구분됨
metadata = MetaData()


class Base(DeclarativeBase):
    metadata = metadata


def _make_profile_id() -> str:
    """weakness_profile 전용 id를 생성한다. wkp_ prefix + uuid4 조합이다."""
    return f"wkp_{uuid.uuid4().hex}"


def _make_snapshot_id() -> str:
    """weakness_snapshot 전용 id를 생성한다. wks_ prefix + uuid4 조합이다."""
    return f"wks_{uuid.uuid4().hex}"


class WeaknessProfile(Base):
    """사용자별 학습 약점 누적 프로필 모델이다.

    topic + subtopic + user_id 복합 UNIQUE 제약으로 UPSERT를 지원한다.
    severity 1~5 CHECK 제약은 DB 레벨에서 강제한다.
    user_id FK는 Spring이 관리하는 user 테이블을 참조만 한다.
    """

    __tablename__ = "weakness_profile"
    __table_args__ = (
        # UPSERT(ON CONFLICT) 동작을 위한 복합 UNIQUE 제약
        # subtopic이 NULL인 경우 별도 처리 필요 — NULL은 UNIQUE 비교에서 제외됨
        UniqueConstraint("user_id", "topic", "subtopic", name="uq_weakness_user_topic_subtopic"),
        CheckConstraint("severity BETWEEN 1 AND 5", name="ck_weakness_severity_range"),
        Index("idx_weakness_user_topic", "user_id", "topic"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_make_profile_id)
    # Spring user 테이블 참조 — FastAPI는 직접 관리하지 않음
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subtopic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_pattern: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 약점 발생 횟수 — UPSERT 시 증가
    frequency: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 심각도 1~5 — CHECK 제약으로 범위 보장
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    # 약점 극복 시 설정됨 — NULL이면 미해결 상태
    resolved_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


class WeaknessSnapshot(Base):
    """특정 날짜 기준 토픽별 숙달도 스냅샷 모델이다.

    (user_id, topic, snapshot_date) 복합 UNIQUE로 날짜별 중복 기록을 방지한다.
    mastery는 0.0000~1.0000 범위의 소수로 저장된다.
    """

    __tablename__ = "weakness_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "topic", "snapshot_date",
            name="uq_weakness_snapshot_user_topic_date",
        ),
        # snapshot_date DESC 정렬 인덱스 — 최신 스냅샷 조회 최적화
        Index("idx_weakness_snapshot_user_topic", "user_id", "topic", "snapshot_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_make_snapshot_id)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    # 숙달도 0.0000~1.0000 범위 — Numeric(5,4) 정밀도
    mastery: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
