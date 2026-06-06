"""AssignmentGrader_V1 입출력 스키마."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GradeRequest(BaseModel):
    """Spring이 FastAPI에 보내는 텍스트 채점 요청."""

    # Spring submission PK — sbm_{ULID 26자} 형식
    submission_id: str = Field(min_length=1)
    # 과제 제목 — 채점 프롬프트 컨텍스트용
    assignment_title: str = Field(default="제출 과제")
    # 과제 설명 (채점 기준) — 없으면 범용 기준 사용
    assignment_description: str | None = None
    # 과제 문항 목록 (JSON 배열 파싱 후 문자열 리스트) — 없으면 빈 리스트
    assignment_questions: list[str] = Field(default_factory=list)
    # 학생이 제출한 텍스트 답안
    answer_text: str = Field(min_length=1)


class GradeResponse(BaseModel):
    """채점 요청 수락 응답 — 실제 채점 결과는 Spring 콜백으로 전달된다."""

    # 채점 작업이 백그라운드에서 시작됐음을 의미한다
    accepted: bool
    submission_id: str
