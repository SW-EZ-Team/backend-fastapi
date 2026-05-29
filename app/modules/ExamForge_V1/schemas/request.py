"""API 요청 모델."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ExamConfig(BaseModel):
    """시험 설정."""

    total_questions: int = Field(ge=5, le=100, default=50)
    time_limit_minutes: int = Field(ge=10, le=300, default=60)
    locale: str = "ko"
    category: str = "korean"
    question_types: list[str] = Field(default_factory=lambda: ["ko_multiple_choice_5"])
    difficulty_distribution: dict[int, float] = {
        1: 0.2,
        2: 0.3,
        3: 0.3,
        4: 0.15,
        5: 0.05,
    }
    passing_score: float = 60.0
    include_explanations: bool = True

    @field_validator("difficulty_distribution")
    @classmethod
    def validate_difficulty_distribution(
        cls, v: dict[int, float]
    ) -> dict[int, float]:
        """난이도 분포 항목 수를 최대 10개로 제한하고 합계를 1.0으로 강제한다."""
        if len(v) > 10:
            raise ValueError(
                f"difficulty_distribution 항목은 최대 10개까지 허용됩니다 (현재 {len(v)}개)."
            )
        total = sum(v.values())
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"난이도 분포의 합이 1.0이어야 합니다 (현재: {total:.2f})"
            )
        return v


class ExamForgeRequest(BaseModel):
    """모의고사 생성 요청."""

    # 서비스 거부 공격 방지를 위해 최대 길이를 제한한다
    source_text: str = Field(min_length=100, max_length=50000)
    subject: str = Field(min_length=1, max_length=200)
    exam_config: ExamConfig = ExamConfig()

    @field_validator("source_text")
    @classmethod
    def validate_source_text(cls, v: str) -> str:
        """공백만으로 이루어진 입력을 차단한다."""
        stripped = v.strip()
        if len(stripped) < 100:
            raise ValueError("공백 제거 후 최소 100자 이상이어야 합니다")
        return stripped

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, v: str) -> str:
        """공백만으로 이루어진 과목명을 차단한다."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("과목명은 공백만으로 구성될 수 없습니다")
        return stripped
