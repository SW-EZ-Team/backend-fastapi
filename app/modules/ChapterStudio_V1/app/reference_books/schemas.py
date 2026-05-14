from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReferenceBookPage(BaseModel):
    """OCR 파이프라인이 만든 페이지 단위 텍스트다."""

    model_config = ConfigDict(strict=True, frozen=True)

    page: int = Field(ge=1)
    text: str = Field(default="", max_length=20000)
    source_title: str = Field(default="", max_length=200)


class ReferenceBookHit(BaseModel):
    """강의 생성에 주입할 page-anchored 참고도서 발췌다."""

    model_config = ConfigDict(strict=True, frozen=True)

    page: int = Field(ge=1)
    snippet: str = Field(min_length=1, max_length=700)
    score: float = Field(ge=0.0)
    source_title: str = Field(default="", max_length=200)
    matched_terms: list[str] = Field(default_factory=list, max_length=16)


class ReferenceBookContext(BaseModel):
    """암기노트와 음성대본에 선택적으로 들어가는 참고도서 컨텍스트다."""

    model_config = ConfigDict(strict=True, frozen=True)

    source_title: str = Field(default="", max_length=200)
    query: str = Field(default="", max_length=1000)
    page_count: int = Field(default=0, ge=0)
    ocr_model: str = Field(default="", max_length=80)
    hits: list[ReferenceBookHit] = Field(default_factory=list, max_length=8)

    def has_hits(self) -> bool:
        """생성 프롬프트에 넣을 발췌가 있는지 반환한다."""
        return len(self.hits) > 0
