"""텍스트 생성 전용 요청/응답 스키마 (Pydantic v2).

ChapterStudio 마이그레이션 호환 스키마. AIRequest/AIResponse 와 병행 유지.
도메인별 파일 분리(SRP):
  - schemas.py           : AIRequest/AIResponse, ASR, Denoise, OCR, Correction
  - tts_schemas.py       : TTSRequest / TTSResponse
  - pipeline_schemas.py  : PageResult / OCRPipelineResult
  - postproc_schemas.py  : PostprocRequest / PostprocResponse
  - text_schemas.py (본 파일) : ChapterAIRequest / ChapterAIResponse
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChapterAIRequest(BaseModel):
    """텍스트 커넥터 요청.

    system/user 프롬프트를 분리해 벤더별 system 파라미터에 매핑한다.
    frozen=True 로 불변 객체를 보장해 동시성 환경에서 안전하게 공유한다.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    system: str = ""
    user: str = Field(min_length=1)
    max_tokens: int = Field(ge=1, le=32000)
    temperature: float = Field(ge=0.0, le=2.0)
    extra: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ChapterAIResponse(BaseModel):
    """텍스트 커넥터 응답.

    input_tokens/output_tokens 를 명시해 비용 추적 및 로깅을 단순화한다.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    text: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    finish_reason: str
