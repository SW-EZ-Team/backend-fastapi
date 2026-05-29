"""AI 커넥터 공통 인터페이스.

모든 벤더 커넥터는 AIConnector(텍스트) / ASRConnector(음성→텍스트) /
DenoiseConnector(음성→음성) / TTSConnector(텍스트+레퍼런스→음성) /
OCRConnector(이미지→텍스트) / PostprocConnector(OCR 텍스트→교정 텍스트)
Protocol 중 하나를 구현한다.
호출부는 구체 커넥터를 직접 import하지 않고 registry를 통해 받는다.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .postproc_schemas import PostprocRequest, PostprocResponse
from .schemas import (
    AIRequest,
    AIResponse,
    ASRRequest,
    ASRResponse,
    DenoiseRequest,
    DenoiseResponse,
    OCRRequest,
    OCRResponse,
)
from .tts_schemas import TTSRequest, TTSResponse


@runtime_checkable
class AIConnector(Protocol):
    """벤더 중립 AI 텍스트 생성 커넥터 인터페이스."""

    # 커넥터 식별자 (예: "kanana", "gemini-mac", "qwen3-tts-modal")
    name: str

    async def generate(self, request: AIRequest) -> AIResponse:
        """주어진 요청으로 AI 모델 호출 후 공통 응답 스키마로 반환."""
        ...

    def supports(self, feature: str) -> bool:
        """capability 플래그 검사 (예: 'streaming', 'tool_calling', 'vision')."""
        ...


@runtime_checkable
class ASRConnector(Protocol):
    """벤더 중립 ASR(음성→텍스트) 커넥터 인터페이스.

    AIConnector와는 입력/출력 스키마가 달라 별도 Protocol로 둔다.
    이렇게 하면 타입 체크도 분리되고, 라우터는 명시적으로 ASR만 다룰 수 있다.
    """

    name: str

    async def generate(self, request: ASRRequest) -> ASRResponse:
        """오디오 요청을 받아 트랜스크립트 응답으로 반환."""
        ...

    def supports(self, feature: str) -> bool:
        """capability 플래그 검사 (예: 'transcription', 'language_hint')."""
        ...


@runtime_checkable
class DenoiseConnector(Protocol):
    """벤더 중립 Denoise(음성→음성) 커넥터 인터페이스.

    입력/출력이 모두 오디오 바이트라 ASR과 메서드명을 분리해 혼동을 막는다.
    (AIConnector/ASRConnector는 모두 generate 지만, 여기는 denoise 고유 이름.)
    """

    name: str

    async def denoise(self, request: DenoiseRequest) -> DenoiseResponse:
        """지저분한 오디오를 깨끗한 WAV 바이트로 정제해 반환."""
        ...

    def supports(self, feature: str) -> bool:
        """capability 플래그 검사 (예: 'super_resolution', 'batch')."""
        ...


@runtime_checkable
class TTSConnector(Protocol):
    """벤더 중립 TTS(텍스트+레퍼런스→음성) 커넥터 인터페이스.

    입력은 합성할 텍스트와 레퍼런스 오디오/텍스트 쌍(보이스 클로닝 ICL 모드),
    출력은 WAV 바이트다. ASRConnector/DenoiseConnector와 메서드명을 분리해
    혼동을 막는다(synthesize 고유).
    """

    name: str

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """텍스트 + 레퍼런스 음성으로 합성된 WAV 바이트를 반환한다."""
        ...

    def supports(self, feature: str) -> bool:
        """capability 플래그 검사 (예: 'voice_cloning', 'language_hint')."""
        ...


@runtime_checkable
class OCRConnector(Protocol):
    """벤더 중립 OCR(이미지→텍스트) 커넥터 인터페이스.

    PaddleOCR ONNX, Tesseract, 클라우드 OCR 등 다양한 구현체를 교체 가능하도록
    단일 Protocol 로 추상화한다. 호출부는 구체 구현을 알 필요 없다.
    """

    name: str

    async def recognize(self, req: OCRRequest) -> OCRResponse:
        """이미지 바이트를 받아 텍스트 인식 결과를 반환한다."""
        ...

    def supports(self, feature: str) -> bool:
        """capability 플래그 검사 (예: 'korean', 'layout_analysis', 'pdf')."""
        ...


@runtime_checkable
class PostprocConnector(Protocol):
    """벤더 중립 OCR 후처리 LLM 커넥터 인터페이스.

    OCR raw 출력(반복 붕괴, 오타, 띄어쓰기 오류)을 한국어/수식 문맥으로
    교정한다. 입력/출력이 이미지가 아닌 '텍스트→텍스트' 라서 AIConnector 와
    시그니처가 비슷하나, 반환 스키마가 달라서 별도 Protocol 로 둔다.
    (AIConnector.generate 는 자유 텍스트 생성, PostprocConnector.refine 은
    교정 diff 포함 구조화 응답.)

    대표 구현: Kanana-1.5-2.1B MLX 4bit (로컬 Mac), Qwen3-Modal (향후 서버 fallback).
    """

    name: str

    async def refine(self, req: PostprocRequest) -> PostprocResponse:
        """OCR 텍스트를 받아 교정 결과와 교정 항목 목록을 반환한다."""
        ...

    def supports(self, feature: str) -> bool:
        """capability 플래그 검사 (예: 'korean', 'latex_preserve', 'mlx')."""
        ...
