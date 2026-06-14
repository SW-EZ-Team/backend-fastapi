"""API 요청 모델."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ExamConfig(BaseModel):
    """시험 설정."""

    total_questions: int = Field(ge=5, le=100, default=50)
    time_limit_minutes: int = Field(ge=10, le=300, default=60)
    locale: str = "ko"
    category: str = "korean"
    # 빈 리스트 = 유형 자동 분배(최종모의고사 기본). plan_exam_node가 기본 혼합 유형으로 분배한다.
    # 호출자가 명시적으로 유형을 지정하면 그 목록을 그대로 사용한다.
    question_types: list[str] = Field(default_factory=list)
    # 기본 난이도 분포 — 블룸 3~5(적용·분석·평가) 비중을 높여 실전 난이도를 확보한다
    difficulty_distribution: dict[int, float] = {
        2: 0.2,
        3: 0.35,
        4: 0.3,
        5: 0.15,
    }
    passing_score: float = 60.0
    include_explanations: bool = True
    # True면 최소 20문항 클램프를 우회한다 — 호출자가 의도적으로 작은 시험을 요청한 경우 전용
    allow_small_exam: bool = False

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
