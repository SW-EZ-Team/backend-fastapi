from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChapterAIRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    system: str = ""
    user: str = Field(min_length=1)
    # 상한은 gemini-3.5-flash 실제 output_token_limit(65536)에 맞춘다.
    # 긴 레슨 JSON은 thinking 토큰까지 더해 24000을 넘기 쉬워 충분한 헤드룸이 필요하다.
    max_tokens: int = Field(ge=1, le=65536)
    temperature: float = Field(ge=0.0, le=2.0)
    extra: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ChapterAIResponse(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    text: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    finish_reason: str
