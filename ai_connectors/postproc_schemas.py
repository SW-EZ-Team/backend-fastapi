"""OCR 후처리 LLM 커넥터 전용 스키마 (Pydantic v2).

PostprocConnector(base.py) 의 입출력 스키마를 정의한다.
Correction 은 schemas.py 에 두고 양쪽에서 import 해 재사용한다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas import Correction


class PostprocRequest(BaseModel):
    """OCR 후처리 LLM 요청 공통 스키마.

    ocr_text 는 OCRResponse.text 를 그대로 넣을 것을 가정한다 (줄바꿈 보존).
    preserve_latex=True 이면 `$...$`, `\\[...\\]`, `\\(...\\)` 블록을 LLM 이
    재작성하지 않도록 프롬프트에 명시 지시를 추가한다. 한국어 교정 과정에서
    수식 토큰이 망가지는 사고를 방지하는 안전장치다.
    """

    ocr_text: str = Field(..., min_length=1, description="OCR raw 출력 문자열")
    preserve_latex: bool = Field(
        default=True,
        description="LaTeX 수식 블록 원형 보존 여부 (기본 True)",
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        description="생성 최대 토큰 수. 미지정 시 커넥터 기본값 사용",
    )
    language_hint: str = Field(
        default="ko",
        description="ISO 639-1 언어 힌트. 한국어 외 교정 시 오버라이드",
    )


class PostprocResponse(BaseModel):
    """OCR 후처리 LLM 응답 공통 스키마.

    refined_text 는 교정 후 최종 텍스트,
    corrections 는 교정 항목 리스트 (UI diff/감사 로그용).
    hallucination_suspect=True 이면 호출자는 raw 로 fallback 하거나
    재시도를 고려해야 한다. 판정 기준은 probe 스크립트와 동일하게
    '결과 길이가 원문 대비 20% 이상 증가' 휴리스틱이다.
    """

    refined_text: str = Field(..., description="교정 후 최종 텍스트")
    corrections: list[Correction] = Field(
        default_factory=list,
        description="적용된 교정 항목 목록",
    )
    hallucination_suspect: bool = Field(
        default=False,
        description="길이 휴리스틱으로 할루시네이션 의심 판정 결과",
    )
    model: str = Field(..., description="실제 추론에 사용된 모델 식별자")
    latency_ms: float = Field(..., description="서버 측 추론 지연 시간(ms)")
    input_char_count: int = Field(
        ...,
        ge=0,
        description="입력 OCR 텍스트 문자 수",
    )
    output_char_count: int = Field(
        ...,
        ge=0,
        description="출력 refined_text 문자 수",
    )
