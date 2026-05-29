"""TTS V2 — V1 ASR 기반 QC 커넥터.

Qwen3-ASR MLX 모델을 사용해 오디오를 전사하고 CER 로 품질을 판정한다.
ASR 모델이 로드되지 않은 환경에서는 "asr_unavailable" 을 반환하고
파이프라인을 블로킹하지 않는다.

V1 의 compute_cer / normalize_for_compare 를 재사용해 품질 기준을 통일한다.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass

from ai_connectors.tts._quality_gate import compute_cer
from common.logging import get_logger
from app.modules.TTS_V2.connectors._qc_utils import (
    ensure_float32_mono,
    resample_to_16k,
    strip_ref_prefix,
    check_repetition,
    check_speed_anomaly,
    check_excessive_silence,
)

logger = get_logger(__name__)

# ASR 모델 가용 여부를 dict 홀더로 캐싱 — global 문 없이 변경 가능
_STATE: dict[str, bool | None] = {"asr_available": None}


@dataclass(frozen=True, slots=True)
class ASRV1QCResult:
    """V1 ASR 기반 QC 결과.

    asr_unavailable 이면 passed=False 이지만 파이프라인은 계속 진행한다.
    """

    transcript: str
    cer: float
    passed: bool
    # "ok" / "high_cer" / "speed_anomaly" / "excessive_silence"
    # / "repetition" / "asr_unavailable"
    reason: str


class ASRV1QC:
    """V1 ASR round-trip QC. Qwen3-ASR MLX 기반.

    모델이 없는 환경에서는 즉시 "asr_unavailable" 을 반환해 파이프라인을 막지 않는다.
    모델이 있으면 전사 후 compute_cer 로 품질을 판정한다.
    """

    @classmethod
    def evaluate(
        cls, audio_np: np.ndarray, sample_rate: int, expected_text: str,
        cer_threshold: float = 0.20, ko_cps_min: float = 3.0,
        ko_cps_max: float = 10.0, silence_max_ratio: float = 0.3,
        ref_text: str = "",
    ) -> ASRV1QCResult:
        """V1 ASR 로 전사하고 CER 기반 품질을 판정한다.

        ref_text 가 비어 있지 않으면 ICL 모드로 간주하고, 전사 결과에서
        레퍼런스 꼬리를 제거한 뒤 CER 을 계산한다.
        """
        if not _is_asr_available():
            logger.warning("Qwen3-ASR 모델 미로드 — QC 건너뜀 (asr_unavailable)")
            return ASRV1QCResult(transcript="", cer=0.0, passed=False, reason="asr_unavailable")
        audio_f32 = ensure_float32_mono(audio_np)
        audio_f32 = resample_to_16k(audio_f32, sample_rate)
        duration_sec = len(audio_np) / max(sample_rate, 1)
        transcript = _run_asr(audio_f32)
        # ICL 모드: 레퍼런스 꼬리가 전사 앞에 붙으므로 제거 후 CER 비교
        cleaned = strip_ref_prefix(transcript, expected_text) if ref_text else transcript
        cer = compute_cer(cleaned, expected_text)
        reason = _determine_reason(
            transcript=transcript, expected_text=expected_text, audio_np=audio_np,
            duration_sec=duration_sec, cer=cer, cer_threshold=cer_threshold,
            ko_cps_min=ko_cps_min, ko_cps_max=ko_cps_max,
            silence_max_ratio=silence_max_ratio,
        )
        return ASRV1QCResult(transcript=transcript, cer=cer, passed=(reason == "ok"), reason=reason)


# ─── 내부 헬퍼 함수 ──────────────────────────────────────────────────────────


def _is_asr_available() -> bool:
    """Qwen3-ASR 패키지와 모델이 사용 가능한지 확인한다. 결과를 캐싱한다."""
    # dict 홀더로 접근 — global 문 불필요
    if _STATE["asr_available"] is not None:
        return _STATE["asr_available"]
    try:
        import mlx_qwen3_asr
        _ = mlx_qwen3_asr  # 패키지 가용성만 확인; 실제 사용은 _run_asr() 에서 수행
        _STATE["asr_available"] = True
    except ImportError:
        _STATE["asr_available"] = False
        logger.info("mlx_qwen3_asr 패키지 없음 — ASRV1QC 비활성화")
    return _STATE["asr_available"]


def _run_asr(audio_f32: np.ndarray) -> str:
    """Qwen3-ASR 로 float32 모노 16kHz 오디오를 전사한다.

    mlx_qwen3_asr.transcribe 는 TranscriptionResult 데이터클래스를 반환한다.
    .text 속성이 있으면 그것을 사용하고, dict 이면 'text' 키로 추출한다.
    """
    try:
        import mlx_qwen3_asr
        result = mlx_qwen3_asr.transcribe(audio_f32, language="ko")
        if hasattr(result, "text"):
            return (result.text or "").strip()
        if isinstance(result, dict):
            return result.get("text", "").strip()
        return ""
    except Exception as exc:
        logger.warning("Qwen3-ASR 전사 실패: %s", exc)
        return ""


def _determine_reason(
    transcript: str,
    expected_text: str,
    audio_np: np.ndarray,
    duration_sec: float,
    cer: float,
    cer_threshold: float,
    ko_cps_min: float,
    ko_cps_max: float,
    silence_max_ratio: float,
) -> str:
    """V1 ASR QC 판정 이유를 우선순위 순으로 결정한다."""
    if check_repetition(transcript):
        return "repetition"
    # 속도 판정은 실제 발화량(전사 텍스트)을 기준으로 한다
    if check_speed_anomaly(transcript, duration_sec, ko_cps_min, ko_cps_max):
        return "speed_anomaly"
    if check_excessive_silence(audio_np, silence_max_ratio):
        return "excessive_silence"
    if cer > cer_threshold:
        return "high_cer"
    return "ok"
