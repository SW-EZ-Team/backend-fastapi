"""TTS V2 — WhisperX QC 커넥터.

Mac 환경에서는 whisperx 대신 mlx_whisper(MLX 네이티브)를 백엔드로 사용한다.
인터페이스는 동일하게 유지해 qc_node 의 엔진 선택 로직과 분리된다.
싱글톤 패턴으로 모델을 한 번만 등록해 반복 호출 시 다운로드 오버헤드를 막는다.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass

from ai_connectors.tts._quality_gate import compute_cer
from ai_connectors.errors import ModelLoadError, InferenceError
from common.logging import get_logger
from app.modules.TTS_V2.connectors._qc_utils import (
    ensure_float32_mono,
    resample_to_16k,
    strip_ref_prefix,
    compute_wer,
    determine_qc_reason,
)

logger = get_logger(__name__)

# WhisperX 모델 크기 → mlx-community HF 레포 이름 매핑.
# "large-v3" 는 mlx-community 에 존재하지 않으므로 turbo 변형으로 대체한다.
# turbo 는 large-v3 와 동일 가중치의 경량화 버전으로 품질 차이가 미미하다.
_MODEL_REPO_MAP: dict[str, str] = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base",
    "small": "mlx-community/whisper-small",
    "medium": "mlx-community/whisper-medium",
    "large-v2": "mlx-community/whisper-large-v2",
    "large-v3": "mlx-community/whisper-large-v3-turbo",    # mlx-community 에 v3 비공개 → turbo 대체
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}


@dataclass(frozen=True, slots=True)
class WhisperXQCResult:
    """WhisperX QC 결과.

    word_segments 는 mlx_whisper 가 word_timestamps=True 일 때 반환하는
    단어 수준 타임스탬프 목록이다. 미지원 환경에서는 빈 리스트가 된다.
    """

    transcript: str
    cer: float
    wer: float
    word_segments: list[dict]
    passed: bool
    # "ok" / "high_cer" / "high_wer" / "speed_anomaly"
    # / "excessive_silence" / "repetition"
    reason: str


class WhisperXQC:
    """mlx_whisper 기반 QC 커넥터. 싱글톤 모델 레포 등록.

    Mac MLX 백엔드를 사용하므로 device/compute_type 인자는 호환용으로만 보존한다.
    실제 모델 다운로드는 첫 evaluate() 호출 시 mlx_whisper 내부에서 처리된다.
    """

    _model_repo: str | None = None
    _loaded: bool = False

    @classmethod
    def load_model(
        cls,
        model_size: str = "large-v3",
        device: str = "cpu",           # mlx_whisper 는 device 미사용, 호환용
        compute_type: str = "float32", # 동일 이유로 보존
    ) -> None:
        """mlx_whisper 가 사용할 HF 레포 이름을 등록한다."""
        repo = _MODEL_REPO_MAP.get(model_size)
        if repo is None:
            raise ModelLoadError(
                f"지원하지 않는 모델 크기: {model_size!r}. "
                f"사용 가능: {list(_MODEL_REPO_MAP)}"
            )
        cls._model_repo = repo
        cls._loaded = True
        logger.info("WhisperXQC 모델 레포 등록: %s", repo)

    @classmethod
    def unload_model(cls) -> None:
        """모델 레퍼런스를 해제해 메모리 압력을 낮춘다."""
        cls._model_repo = None
        cls._loaded = False
        logger.info("WhisperXQC 모델 언로드 완료")

    @classmethod
    def evaluate(
        cls, audio_np: np.ndarray, sample_rate: int, expected_text: str,
        cer_threshold: float = 0.20, wer_threshold: float = 0.25,
        ko_cps_min: float = 3.0, ko_cps_max: float = 10.0,
        silence_max_ratio: float = 0.3,
        ref_text: str = "",
    ) -> WhisperXQCResult:
        """오디오를 전사하고 expected_text 와 비교해 품질을 판정한다.

        ref_text 가 비어 있지 않으면 ICL 모드로 간주하고, 전사 결과에서
        레퍼런스 꼬리를 제거한 뒤 CER/WER 을 계산한다.
        속도 판정은 전사 전체(실제 발화량)를 기준으로 한다.
        """
        if not cls._loaded or cls._model_repo is None:
            cls.load_model()
        assert cls._model_repo is not None  # load_model() 내에서 항상 설정됨
        transcript, word_segs = _transcribe(audio_np, sample_rate, cls._model_repo)
        # ICL 모드: 레퍼런스 꼬리가 전사 앞에 붙으므로 제거 후 CER/WER 비교
        cleaned = strip_ref_prefix(transcript, expected_text) if ref_text else transcript
        cer = compute_cer(cleaned, expected_text)
        wer = compute_wer(cleaned, expected_text)
        duration_sec = len(audio_np) / max(sample_rate, 1)
        reason = determine_qc_reason(
            transcript=transcript, expected_text=expected_text, audio_np=audio_np,
            duration_sec=duration_sec, cer=cer, wer=wer,
            cer_threshold=cer_threshold, wer_threshold=wer_threshold,
            ko_cps_min=ko_cps_min, ko_cps_max=ko_cps_max,
            silence_max_ratio=silence_max_ratio,
        )
        return WhisperXQCResult(
            transcript=transcript, cer=cer, wer=wer,
            word_segments=word_segs, passed=(reason == "ok"), reason=reason,
        )


def _transcribe(
    audio_np: np.ndarray,
    sample_rate: int,
    model_repo: str,
) -> tuple[str, list[dict]]:
    """mlx_whisper 로 오디오 배열을 전사해 (텍스트, 단어 세그먼트) 를 반환한다."""
    try:
        import mlx_whisper
    except ImportError as exc:
        raise ModelLoadError("mlx_whisper 패키지가 설치되지 않았습니다.") from exc

    audio_f32 = ensure_float32_mono(audio_np)
    audio_f32 = resample_to_16k(audio_f32, sample_rate)
    raw = _call_mlx_whisper(mlx_whisper, audio_f32, model_repo)
    transcript: str = raw.get("text", "").strip()
    word_segs = _extract_word_segments(raw)
    return transcript, word_segs


def _call_mlx_whisper(mlx_whisper, audio_f32: np.ndarray, model_repo: str) -> dict:
    """mlx_whisper.transcribe 를 호출하고 raw 결과 dict 를 반환한다."""
    try:
        return mlx_whisper.transcribe(
            audio_f32,
            path_or_hf_repo=model_repo,
            language="ko",
            word_timestamps=True,
            verbose=None,
        )
    except Exception as exc:
        raise InferenceError(f"mlx_whisper 전사 실패: {exc}") from exc


def _extract_word_segments(result: dict) -> list[dict]:
    """전사 결과에서 단어 수준 타임스탬프 목록을 추출한다."""
    word_segs: list[dict] = []
    for seg in result.get("segments", []):
        word_segs.extend(seg.get("words", []))
    return word_segs
