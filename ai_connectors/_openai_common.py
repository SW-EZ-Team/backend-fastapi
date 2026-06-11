"""OpenAI 커넥터 공통 헬퍼.

openai SDK 호출에 필요한 인증, 지연 import, 클라이언트 생성을 한곳에 모은다.
Gemini 장애 시 자동 폴백으로 동작하므로 _gemini_common 과 동일한 패턴을 따른다.
커넥터 인스턴스 생성 단계에서는 API 키를 읽지 않아 오프라인 테스트와 레지스트리
검증이 실제 시크릿 주입 여부와 분리된다.

PCM/WAV 변환은 _gemini_common 의 헬퍼를 그대로 재사용한다(중복 구현 금지).
"""
from __future__ import annotations

import io
import wave

from ._gemini_common import (  # noqa: F401 — 커넥터가 import 경로를 _openai_common 으로 공유한다
    pcm16_duration_sec,
    pcm16_mono_to_wav,
)
from .errors import AuthError, InferenceError, ModelLoadError

import os


def openai_api_key() -> str:
    """OPENAI_API_KEY 를 읽는다. Gemini 와 달리 Google 식 대체 키는 두지 않는다."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise AuthError("OPENAI_API_KEY 가 설정되지 않았습니다.")
    return key


def load_openai_module() -> object:
    """openai SDK 를 호출 시점에 import 한다."""
    try:
        import openai
    except ImportError as exc:
        raise ModelLoadError(
            "openai 패키지가 설치되어 있지 않습니다. "
            "`uv add openai` 실행 필요"
        ) from exc
    return openai


def build_openai_client() -> tuple[object, object]:
    """동기 OpenAI 클라이언트와 openai 모듈 객체를 함께 반환한다.

    멀티모달(OCR)·전사(ASR)·음성(TTS) 커넥터가 모두 동기 SDK 를 쓰고
    asyncio.to_thread 로 감싸므로, Gemini 와 동일하게 동기 클라이언트를 돌려준다.
    """
    openai = load_openai_module()
    client = openai.OpenAI(api_key=openai_api_key())
    return client, openai


def build_async_openai_client() -> tuple[object, object]:
    """비동기 AsyncOpenAI 클라이언트와 openai 모듈 객체를 함께 반환한다.

    텍스트 커넥터는 ClaudeSonnetConnector 와 동일하게 비동기 클라이언트를 직접 await 한다.
    """
    openai = load_openai_module()
    client = openai.AsyncOpenAI(api_key=openai_api_key())
    return client, openai


def wav_duration_sec(wav_bytes: bytes) -> float:
    """WAV 바이트의 헤더를 읽어 재생 시간을 초 단위로 반환한다.

    OpenAI TTS 는 response_format="wav" 로 WAV 바이트를 직접 돌려준다.
    PCM 길이를 모르므로 wave 헤더(프레임 수 / 샘플레이트)로 길이를 계산한다.
    """
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            frames = wf.getnframes()
            sample_rate = wf.getframerate()
    except (wave.Error, EOFError) as exc:
        raise InferenceError("OpenAI TTS WAV 헤더를 해석하지 못했습니다.") from exc
    if sample_rate <= 0:
        raise InferenceError("OpenAI TTS WAV 샘플레이트가 올바르지 않습니다.")
    return frames / float(sample_rate)
