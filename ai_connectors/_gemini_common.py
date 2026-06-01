"""Gemini 커넥터 공통 헬퍼.

google-genai SDK 호출에 필요한 인증, 지연 import, PCM 변환을 한곳에 모은다.
커넥터 인스턴스 생성 단계에서는 API 키를 읽지 않아 오프라인 테스트와 레지스트리
검증이 실제 시크릿 주입 여부와 분리된다.
"""
from __future__ import annotations

import io
import os
import wave

from .errors import AuthError, InferenceError, ModelLoadError


def google_api_key() -> str:
    """GOOGLE_API_KEY 를 반환하고 누락/빈 값은 AuthError 로 정규화한다."""
    try:
        key = os.environ["GOOGLE_API_KEY"].strip()
    except KeyError as exc:
        raise AuthError("GOOGLE_API_KEY 가 설정되지 않았습니다.") from exc
    if not key:
        raise AuthError("GOOGLE_API_KEY 가 비어 있습니다.")
    return key


def load_genai_module() -> object:
    """google-genai SDK 를 호출 시점에 import 한다."""
    try:
        from google import genai
    except ImportError as exc:
        raise ModelLoadError(
            "google-genai 패키지가 설치되어 있지 않습니다. "
            "`uv pip install google-genai` 실행 필요"
        ) from exc
    return genai


def build_genai_client() -> tuple[object, object]:
    """공식 SDK 클라이언트와 genai 모듈 객체를 함께 반환한다."""
    genai = load_genai_module()
    client = genai.Client(api_key=google_api_key())
    return client, genai


def pcm16_mono_to_wav(pcm_data: bytes, sample_rate: int = 24000) -> bytes:
    """Gemini TTS 의 16-bit mono PCM 바이트에 WAV 헤더를 붙인다."""
    if len(pcm_data) % 2 != 0:
        raise InferenceError("Gemini TTS PCM 길이가 16-bit 프레임과 맞지 않습니다.")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def pcm16_duration_sec(pcm_data: bytes, sample_rate: int = 24000) -> float:
    """16-bit mono PCM 바이트 길이를 초 단위 재생 시간으로 변환한다."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if len(pcm_data) % 2 != 0:
        raise InferenceError("Gemini TTS PCM 길이가 16-bit 프레임과 맞지 않습니다.")
    return (len(pcm_data) // 2) / float(sample_rate)
