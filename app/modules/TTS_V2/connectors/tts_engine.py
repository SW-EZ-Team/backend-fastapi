"""TTS V2 — TTS 엔진 세션 커넥터.

V1 의 _mlx_audio_runtime 을 래핑한다.
레퍼런스 오디오를 세션 생성 시 한 번만 디코딩하고 청크 합성마다 재사용한다.
V1 은 run_generate 호출마다 ref_audio numpy 를 받아 내부적으로 WAV 스풀을 처리하므로,
우리는 bytes → numpy 변환을 세션 init 에서 딱 한 번 수행한다.
"""
from __future__ import annotations

import threading
from typing import Any

import numpy as np

from ai_connectors.tts._generation_profile import GenerationProfile
from common.audio_io import ensure_mono, load_audio_from_bytes
from common.logging import get_logger

_LOG = get_logger(__name__)

# 기본 레퍼런스 오디오 샘플레이트 — Qwen3-TTS ICL 모드 기대값
_DEFAULT_REF_SR = 24000

# 기본 생성 파라미터 — 오디오북용 보수적 값
_DEFAULT_PROFILE = GenerationProfile(
    temperature=0.9,
    top_k=50,
    top_p=1.0,
    repetition_penalty=1.05,
)

# 모델 싱글톤 — dict 홀더 패턴으로 PLW0603(global 문) 경고 없이 모듈 레벨 공유 상태를 구현한다
_model_lock = threading.Lock()
_STATE: dict[str, Any] = {}


def _get_or_load_model() -> Any:
    """싱글톤 모델 인스턴스를 반환한다. 최초 호출 시에만 build_model 을 실행한다."""
    if _STATE.get("model") is not None:
        return _STATE["model"]
    with _model_lock:
        # double-checked locking — lock 진입 후 재확인
        if _STATE.get("model") is None:
            from ai_connectors.tts._mlx_audio_runtime import build_model
            _LOG.info("Qwen3-TTS 모델 최초 로드 시작")
            _STATE["model"] = build_model()
            _LOG.info("Qwen3-TTS 모델 로드 완료 (싱글톤)")
    return _STATE["model"]


class TTSEngineSession:
    """단일 레퍼런스 화자에 대한 TTS 합성 세션.

    context manager 로 사용한다:
        with TTSEngineSession(ref_bytes, ref_text, ref_sr) as session:
            audio, sr = session.synthesize_chunk("안녕하세요.")

    ref_audio 를 세션 생성 시 한 번만 numpy 로 변환해 두고
    synthesize_chunk 호출마다 재사용한다. 모델은 첫 합성 요청 시 지연 로드된다.
    """

    def __init__(
        self,
        ref_audio_bytes: bytes,
        ref_text: str,
        ref_sr: int = _DEFAULT_REF_SR,
        language: str = "ko",
    ) -> None:
        """레퍼런스 오디오를 디코딩해 캐싱한다."""
        self._ref_text = ref_text
        self._language = language
        effective_sr = ref_sr if ref_sr > 0 else _DEFAULT_REF_SR
        ref_np, actual_sr = load_audio_from_bytes(ref_audio_bytes, target_sr=effective_sr)
        self._ref_sr = actual_sr
        self._ref_audio: np.ndarray = ensure_mono(ref_np)
        _LOG.debug(
            "TTSEngineSession 초기화: ref_audio shape=%s sr=%d lang=%s",
            self._ref_audio.shape,
            self._ref_sr,
            self._language,
        )

    def __enter__(self) -> TTSEngineSession:
        return self

    def __exit__(self, *args: object) -> None:
        # 현재 cleanup 자원 없음; 향후 GPU 메모리 해제 등 확장 포인트
        pass

    def synthesize_chunk(
        self,
        text: str,
        speed: float = 1.0,
        profile: GenerationProfile | None = None,
    ) -> tuple[np.ndarray, int]:
        """단일 청크를 합성해 (mono float32 numpy, sample_rate) 로 반환한다.

        ref_audio numpy 배열을 재사용하므로 V1 run_generate 의 WAV 스풀은
        내부에서 한 번만 일어난다 (V1 가 호출 내부에서 tempfile 을 사용함).
        """
        from ai_connectors.tts._mlx_audio_runtime import run_generate
        p = profile or _DEFAULT_PROFILE
        model = _get_or_load_model()
        return run_generate(
            model=model,
            text=text,
            ref_audio=self._ref_audio,
            ref_sr=self._ref_sr,
            ref_text=self._ref_text,
            language=self._language,
            speed=speed,
            temperature=p.temperature,
            top_k=p.top_k,
            top_p=p.top_p,
            repetition_penalty=p.repetition_penalty,
        )
