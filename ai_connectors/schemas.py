"""커넥터 공통 요청/응답 스키마 (Pydantic v2 기준).

AI/ASR/Denoise/OCR 공통 입출력 스키마와 Correction 을 정의한다.
도메인별 파일 분리 (SRP 준수):
  - tts_schemas.py     : TTSRequest / TTSResponse
  - pipeline_schemas.py: PageResult / OCRPipelineResult
  - postproc_schemas.py: PostprocRequest / PostprocResponse
backend-fastapi와 동일한 pydantic 2.12.5를 사용하므로 이동 시 호환 문제 없다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AIRequest(BaseModel):
    """AI 텍스트 생성 요청 공통 스키마.

    extra 필드로 벤더별 고유 파라미터를 담을 수 있다 (예: top_p, stop sequences).
    """

    prompt: str = Field(..., description="입력 프롬프트")
    model: str | None = Field(
        default=None,
        description="모델명. 미지정 시 .env의 AI_MODEL 사용",
    )
    max_tokens: int | None = Field(default=None, ge=1, description="최대 토큰 수")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="벤더별 추가 파라미터",
    )


class AIResponse(BaseModel):
    """AI 텍스트 생성 응답 공통 스키마."""

    text: str = Field(..., description="생성된 텍스트")
    model: str = Field(..., description="실제 응답을 생성한 모델명")
    usage: dict[str, Any] | None = Field(
        default=None,
        description="토큰 사용량 등 메타데이터",
    )
    raw: dict[str, Any] | None = Field(
        default=None,
        description="디버깅용 원본 응답 (프로덕션 이동 시 제거 검토)",
    )


class ASRRequest(BaseModel):
    """ASR(음성→텍스트) 요청 공통 스키마.

    audio_bytes는 바이트 원본으로 전달받고, 커넥터 내부에서 16kHz mono로 정규화한다.
    """

    # bytes는 pydantic에서 기본 직렬화 불가 — 내부 전달용이므로 arbitrary_types 허용
    model_config = ConfigDict(arbitrary_types_allowed=True)

    audio_bytes: bytes = Field(..., description="업로드된 오디오 원본 바이트")
    language: str = Field(default="ko", description="ISO 639-1 언어 코드")
    sample_rate: int | None = Field(
        default=None,
        description="원본 샘플레이트 힌트. 미지정 시 librosa가 파일에서 감지",
    )


class ASRResponse(BaseModel):
    """ASR 응답 공통 스키마."""

    text: str = Field(..., description="변환된 트랜스크립트")
    language: str = Field(..., description="실제 사용된 언어 코드")
    duration_sec: float = Field(..., description="입력 오디오 길이(초)")
    latency_ms: float = Field(..., description="서버 측 추론 지연 시간(ms)")
    model: str = Field(..., description="실제 응답을 생성한 모델 식별자")


class DenoiseRequest(BaseModel):
    """Denoise(음성 정제) 요청 공통 스키마.

    audio_bytes는 바이트 원본이고, 커넥터 내부에서 48kHz mono로 정규화한다.
    apply_super_resolution=True 이면 SE 출력 → SR 모델로 한 번 더 후처리한다.
    """

    # bytes는 기본 직렬화 불가 — 내부 전달용
    model_config = ConfigDict(arbitrary_types_allowed=True)

    audio_bytes: bytes = Field(..., description="업로드된 오디오 원본 바이트")
    sample_rate: int | None = Field(
        default=None,
        description="원본 샘플레이트 힌트. 미지정 시 librosa가 파일에서 감지",
    )
    apply_super_resolution: bool = Field(
        default=False,
        description="SE 뒤에 SR(48K) 후처리 파이프라인 on/off",
    )


class DenoiseResponse(BaseModel):
    """Denoise 응답 공통 스키마.

    audio_bytes는 WAV 포맷(16-bit PCM mono 48kHz)으로 인코딩된 결과물이다.
    라우터가 StreamingResponse로 바이너리 응답을 내보내기 직전에 참조한다.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    audio_bytes: bytes = Field(..., description="WAV 인코딩된 정제본 바이트")
    sample_rate: int = Field(default=48000, description="출력 샘플레이트(Hz)")
    content_type: str = Field(default="audio/wav", description="MIME 타입")
    duration_sec: float = Field(..., description="정제본 오디오 길이(초)")
    latency_ms: float = Field(..., description="서버 측 추론 지연 시간(ms)")
    super_resolution_applied: bool = Field(
        default=False, description="SR 후처리 적용 여부"
    )
    model: str = Field(..., description="실제 응답을 생성한 모델 식별자")


class OCRDetection(BaseModel):
    """단일 텍스트 영역 인식 결과."""

    text: str = Field(..., description="인식된 텍스트 문자열")
    bbox: list[int] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="바운딩 박스 [x1, y1, x2, y2] (픽셀 좌표)",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="인식 신뢰도 (0.0~1.0)",
    )


class OCRRequest(BaseModel):
    """OCR 요청 공통 스키마.

    image_bytes 는 PNG/JPEG/WebP 등 Pillow 가 읽을 수 있는 형식을 허용한다.
    커넥터 내부에서 필요한 전처리(RGB 변환, 리사이즈 등)를 수행한다.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    image_bytes: bytes = Field(..., description="이미지 원본 바이트")
    language: str = Field(
        default="ko",
        description="ISO 639-1 언어 코드. PaddleOCR 한국어 모델 선택에 참조",
    )


class OCRResponse(BaseModel):
    """OCR 응답 공통 스키마.

    detections 는 감지된 텍스트 영역 목록이고,
    text 는 모든 감지 결과를 줄바꿈으로 이어붙인 집계 텍스트다.
    """

    detections: list[OCRDetection] = Field(
        default_factory=list,
        description="감지된 텍스트 영역 목록 (bbox + text + confidence)",
    )
    text: str = Field(
        default="",
        description="전체 인식 텍스트 집계 (줄바꿈 구분)",
    )
    model_version: str = Field(
        ...,
        description="실제 추론에 사용된 모델 식별자 (예: 'paddle-v5-onnx')",
    )
    latency_ms: float = Field(..., description="서버 측 추론 지연 시간(ms)")
    page_count: int = Field(
        default=1,
        ge=1,
        description="처리된 페이지 수 (단일 이미지=1, PDF=페이지 수)",
    )


class Correction(BaseModel):
    """Kanana 후처리가 수행한 단일 교정 항목.

    OCRPipelineResult(pipeline_schemas.py)와 PostprocResponse(postproc_schemas.py)
    양쪽에서 공유하는 공통 교정 단위 스키마다. reason 은 교정 유형 분류
    ('typo' / 'spacing' / 'latex' / 'uncertain' / 'reconstructed' 등).
    """

    original: str = Field(..., description="원본 OCR 인식 텍스트")
    corrected: str = Field(..., description="Kanana 교정 후 텍스트")
    reason: str = Field(default="", description="교정 이유/유형 태그")
