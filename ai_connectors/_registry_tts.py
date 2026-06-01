"""TTS(텍스트-음성 변환) 커넥터 서브레지스트리.

TTS_CONNECTORS dict, 환경변수 파싱 헬퍼, get_tts_connector 팩토리를 담는다.
mlx-audio-qwen3-tts 는 ASR 커넥터 주입이 필요해 전용 팩토리(_make_mlx_tts_connector)를 사용한다.
외부 코드는 이 파일을 직접 import 하지 않고 ai_connectors.registry 를 사용한다.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

from .base import TTSConnector
from .errors import ModelNotFoundError
from .tts.gemini_tts_connector import GeminiTTSConnector
from .tts.mlx_audio_qwen3_tts_connector import MLXAudioQwen3TTSConnector
from .tts.qwen3_tts_modal_connector import Qwen3TTSModalConnector

_LOG = logging.getLogger(__name__)

# TTS 커넥터 팩토리 맵 (TTSConnector 구현체)
TTS_CONNECTORS: dict[str, Callable[[], TTSConnector]] = {
    "gemini-tts": lambda: GeminiTTSConnector(),
    "mlx-audio-qwen3-tts": lambda: MLXAudioQwen3TTSConnector(),
    "qwen3-tts-modal": lambda: Qwen3TTSModalConnector(),
}


def _env_bool(name: str, default: bool) -> bool:
    """환경변수 bool 파싱. 미설정/빈 값은 default 를 반환한다."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    """환경변수 float 파싱. 잘못된 값은 default 로 되돌린다."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        _LOG.warning("%s=%r float 파싱 실패 — 기본값 %.3f 사용", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    """환경변수 int 파싱. 잘못된 값은 default 로 되돌린다."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        _LOG.warning("%s=%r int 파싱 실패 — 기본값 %d 사용", name, raw, default)
        return default


def _make_mlx_tts_connector() -> MLXAudioQwen3TTSConnector:
    """mlx-audio-qwen3-tts 커넥터를 ASR 주입 후 생성한다.

    ASR 커넥터 미등록 시 None 으로 fallback — TTS 자체 동작은 유지된다.
    순환 import 방지를 위해 get_asr_connector 를 지연 import 한다.
    기본 추론 파라미터는 실제 ref_audio 벤치에서 통과한 배포 후보값을 사용한다.
    """
    # 지연 import — _registry_asr 와의 모듈 레벨 순환 참조를 피한다
    from ._registry_asr import get_asr_connector

    asr_model = os.getenv("AI_MODEL_ASR", "asr-fallback")
    try:
        asr_instance = get_asr_connector(asr_model)
    except ModelNotFoundError:
        asr_instance = None
    return MLXAudioQwen3TTSConnector(
        asr=asr_instance,
        temperature=_env_float("TTS_TEMPERATURE", 0.8),
        top_k=_env_int("TTS_TOP_K", 40),
        top_p=_env_float("TTS_TOP_P", 0.95),
        repetition_penalty=_env_float("TTS_REPETITION_PENALTY", 1.1),
        postprocess=_env_bool("TTS_POSTPROCESS", True),
    )


def get_tts_connector(model_name: str | None = None) -> TTSConnector:
    """.env 의 AI_MODEL_TTS 또는 명시된 model_name 으로 TTS 커넥터 반환."""
    name = model_name or os.getenv("AI_MODEL_TTS", "mlx-audio-qwen3-tts")
    if name not in TTS_CONNECTORS:
        raise ModelNotFoundError(
            f"Unknown TTS model: {name}. Registered: {list(TTS_CONNECTORS.keys())}"
        )
    # mlx-audio-qwen3-tts 는 ASR 주입이 필요해 전용 팩토리 사용
    if name == "mlx-audio-qwen3-tts":
        return _make_mlx_tts_connector()
    return TTS_CONNECTORS[name]()
