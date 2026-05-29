"""TTS 커넥터 전용 요청/응답 스키마 (Pydantic v2).

Qwen3-TTS ICL(In-Context Learning) 보이스 클로닝 모드 전용이다.
공통 스키마(ASRRequest/ASRResponse 등)는 schemas.py 에서 관리한다.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_TEXT_MAX_LEN = 800
_REF_TEXT_MAX_LEN = 500


class TTSRequest(BaseModel):
    """TTS(텍스트+레퍼런스 음성→합성 음성) 요청 공통 스키마.

    Qwen3-TTS ICL 모드로 보이스 클로닝하려면 ref_audio_bytes 와 ref_text 가 모두 필요하다.
    ref_text 가 None 이면 커넥터가 ASR 로 자동 전사를 시도한다.
    ASR 커넥터 미주입 시 x_vector_only_mode=True fallback(품질 저하).
    """

    # bytes는 기본 직렬화 불가 — 내부 전달용
    model_config = ConfigDict(arbitrary_types_allowed=True)

    text: str = Field(
        ...,
        min_length=1,
        max_length=_TEXT_MAX_LEN,
        description="합성할 텍스트",
    )
    ref_audio_bytes: bytes = Field(
        ..., description="레퍼런스 음성 원본 바이트 (10~15초 깨끗한 음성 권장)"
    )
    ref_text: str | None = Field(
        default=None,
        max_length=_REF_TEXT_MAX_LEN,
        description=(
            "레퍼런스 음성 발화 내용(한국어). "
            "None 이면 ASR 커넥터로 자동 전사; 없으면 x_vector_only_mode fallback. "
            f"{_REF_TEXT_MAX_LEN}자 초과 입력은 Pydantic 검증 단계에서 거부된다."
        ),
    )
    ref_sample_rate: int | None = Field(
        default=None,
        description="레퍼런스 원본 샘플레이트 힌트. 미지정 시 파일에서 감지",
    )
    language: str = Field(
        default="auto",
        description="lang_code: auto/korean/english/chinese 등 (Qwen3-TTS 표기)",
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="발화 속도 배수")


class TTSResponse(BaseModel):
    """TTS 응답 공통 스키마.

    audio_bytes 는 WAV(16-bit PCM mono, 모델 기본 24kHz) 인코딩 결과다.
    auto_transcribed=True 이면 ref_text 가 ASR 로 자동 생성된 것이다.
    resolved_ref_text 는 실제 TTS 추론에 사용된 ref_text (자동 전사 포함).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    audio_bytes: bytes = Field(..., description="WAV 인코딩된 합성 음성 바이트")
    sample_rate: int = Field(default=24000, description="출력 샘플레이트(Hz)")
    content_type: str = Field(default="audio/wav", description="MIME 타입")
    duration_sec: float = Field(..., description="합성 음성 길이(초)")
    latency_ms: float = Field(..., description="서버 측 추론 지연 시간(ms)")
    char_count: int = Field(..., ge=0, description="합성에 사용된 입력 문자 수")
    model: str = Field(..., description="실제 응답을 생성한 모델 식별자")
    auto_transcribed: bool = Field(
        default=False,
        description="ref_text 가 ASR 자동 전사로 채워진 경우 True",
    )
    resolved_ref_text: str = Field(
        default="",
        description="실제 TTS 추론에 사용된 ref_text (자동 전사 결과 포함)",
    )
    ref_text_source: str = Field(
        default="client",
        description="실제 ref_text 소스(client/auto_asr/validated_auto_asr/empty_fallback)",
    )
    retry_count: int = Field(default=0, ge=0, description="품질 게이트 재시도 횟수")
    quality_cer: float | None = Field(
        default=None,
        description="ASR round-trip 기반 품질 CER. 게이트 미수행 시 None",
    )
    quality_reason: str = Field(
        default="ok",
        description="품질 게이트 판정 이유(ok/repetition/high_cer/hallucinated_extra 등)",
    )
    segment_count: int = Field(default=1, ge=1, description="내부 생성 세그먼트 수")
