"""로컬 Mac용 Qwen3-TTS (MLX) 보이스 클로닝 커넥터."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import numpy as np

from common.audio_io import duration_sec, encode_wav_bytes, ensure_mono, load_audio_from_bytes
from common.logging import get_logger

from ..errors import InferenceError
from ..tts_schemas import TTSRequest, TTSResponse
from ._asr_bridge import evaluate_audio_quality, resolve_ref_text
from ._generation_profile import GenerationProfile, build_retry_profiles
from ._mlx_audio_runtime import build_model
from ._quality_gate import TTSQualityResult
from ._synthesis_flow import synthesize_segments
from ._text_segmentation import normalize_target_text, split_tts_segments

if TYPE_CHECKING:
    from ..base import ASRConnector

_LOG = get_logger(__name__)
_TARGET_SR = 24000
_SEGMENT_MAX_CHARS = 120


class MLXAudioQwen3TTSConnector:
    """Qwen3-TTS 12Hz 1.7B Base (MLX) 실행 커넥터."""

    name: str = "mlx-audio-qwen3-tts"
    _model: Any | None = None
    _load_lock: asyncio.Lock | None = None

    def __init__(
        self,
        asr: ASRConnector | None = None,
        temperature: float = 0.8,
        top_k: int = 40,
        top_p: float = 0.95,
        repetition_penalty: float = 1.1,
        postprocess: bool = True,
    ) -> None:
        self._asr = asr
        self._temperature = temperature
        self._top_k = top_k
        self._top_p = top_p
        self._repetition_penalty = repetition_penalty
        self._postprocess = postprocess

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """텍스트 + 레퍼런스 음성으로 클로닝된 합성 WAV 를 반환한다."""
        target_text = normalize_target_text(request.text)
        ref_text, auto_transcribed, ref_text_source = await resolve_ref_text(self._asr, request)
        ref_audio, ref_sr = await asyncio.to_thread(load_audio_from_bytes, request.ref_audio_bytes, _TARGET_SR)
        model = await self._ensure_model()
        segments = split_tts_segments(target_text, max_chars=_SEGMENT_MAX_CHARS)
        if not segments:
            raise InferenceError("합성할 텍스트가 비어 있습니다.")
        started_at = time.perf_counter()
        audio_np, sample_rate, retry_count, quality = await self._generate_with_quality_gate(
            model=model,
            target_text=target_text,
            segments=segments,
            ref_audio=ref_audio,
            ref_sr=ref_sr,
            ref_text=ref_text,
            language=request.language,
            speed=request.speed,
        )
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        if self._postprocess:
            from ._postprocess import postprocess_audio

            audio_np = await asyncio.to_thread(postprocess_audio, audio_np, sample_rate)
        wav_bytes = await asyncio.to_thread(encode_wav_bytes, audio_np, sample_rate)
        return TTSResponse(
            audio_bytes=wav_bytes,
            sample_rate=sample_rate,
            content_type="audio/wav",
            duration_sec=duration_sec(ensure_mono(audio_np), sample_rate),
            latency_ms=latency_ms,
            char_count=len(target_text),
            model=self.name,
            auto_transcribed=auto_transcribed,
            resolved_ref_text=ref_text or "",
            ref_text_source=ref_text_source,
            retry_count=retry_count,
            quality_cer=quality.cer if quality else None,
            quality_reason=quality.reason if quality else "not_checked",
            segment_count=len(segments),
        )

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그."""
        return feature in {"voice_cloning", "language_hint", "auto_transcribe", "quality_gate"}

    async def _generate_with_quality_gate(
        self,
        model: Any,
        target_text: str,
        segments: list[str],
        ref_audio: np.ndarray,
        ref_sr: int,
        ref_text: str | None,
        language: str,
        speed: float,
    ) -> tuple[np.ndarray, int, int, TTSQualityResult | None]:
        """기본 프로필과 보수적 재시도 프로필을 순서대로 시도한다."""
        profiles = build_retry_profiles(
            GenerationProfile(
                temperature=self._temperature,
                top_k=self._top_k,
                top_p=self._top_p,
                repetition_penalty=self._repetition_penalty,
            )
        )
        last_quality: TTSQualityResult | None = None
        for attempt_index, profile in enumerate(profiles):
            audio_np, sample_rate = await asyncio.to_thread(
                synthesize_segments,
                model,
                segments,
                ref_audio,
                ref_sr,
                ref_text,
                language,
                speed,
                profile,
            )
            quality = await evaluate_audio_quality(
                self._asr,
                target_text,
                audio_np,
                sample_rate,
                language,
            )
            if quality is None or quality.passed:
                return audio_np, sample_rate, attempt_index, quality
            last_quality = quality
            _LOG.warning(
                "품질 게이트 실패: 시도=%d, reason=%s, CER=%.3f, 기준=%.3f, 전사=%s",
                attempt_index,
                quality.reason,
                quality.cer,
                quality.threshold,
                quality.transcript[:120],
            )
        raise InferenceError(
            "TTS 품질 게이트 실패: "
            f"reason={last_quality.reason}, CER={last_quality.cer:.3f}, "
            f"transcript={last_quality.transcript[:160]}"
        )

    @classmethod
    async def _ensure_model(cls) -> Any:
        """모델 싱글톤 로드 — 동시 접근은 Lock 으로 직렬화한다."""
        if cls._model is not None:
            return cls._model
        if cls._load_lock is None:
            cls._load_lock = asyncio.Lock()
        async with cls._load_lock:
            if cls._model is not None:
                return cls._model
            cls._model = await asyncio.to_thread(build_model)
            return cls._model
