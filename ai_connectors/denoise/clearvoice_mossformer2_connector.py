"""로컬 Mac용 MossFormer2 SE/SR (clearvoice) 커넥터.

SE_48K 디노이즈 → (옵션) SR_48K 슈퍼해상도 파이프라인.
SE/SR lazy-load 싱글톤. clearvoice가 file path를 요구하므로 tempfile WAV 스풀 사용.
블로킹 호출은 모두 asyncio.to_thread로 위임한다.
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import wavfile

from common.audio_io import (
    duration_sec,
    encode_wav_bytes,
    ensure_mono,
    load_audio_from_bytes,
)
from common.config import (
    get_mossformer2_se_checkpoint_dir,
    get_mossformer2_sr_checkpoint_dir,
)
from common.logging import get_logger

from ..errors import InferenceError, ModelLoadError
from ..schemas import DenoiseRequest, DenoiseResponse

_LOG = get_logger(__name__)

# MossFormer2_SE_48K / SR_48K 모두 48kHz mono 입출력을 기본으로 한다
_TARGET_SR = 48000


class ClearVoiceMossFormer2Connector:
    """MossFormer2_SE_48K 기반 디노이즈 커넥터 (선택적 SR_48K 후처리)."""

    # registry 키와 동일
    name: str = "mossformer2-se-48k"

    # SE 싱글톤 — 프로세스당 1회 로드
    _se_instance: Any | None = None
    # SR 싱글톤 — apply_super_resolution=True 인 요청이 올 때만 lazy load
    _sr_instance: Any | None = None
    # Lock들은 첫 호출 시 생성
    _se_lock: asyncio.Lock | None = None
    _sr_lock: asyncio.Lock | None = None

    async def denoise(self, request: DenoiseRequest) -> DenoiseResponse:
        """오디오 바이트 → 정제된 WAV 바이트."""
        # 1) 오디오 로드 — 48kHz mono 강제 (SR 입력도 48kHz 전제)
        audio, sr = await asyncio.to_thread(
            load_audio_from_bytes, request.audio_bytes, _TARGET_SR
        )
        # 2) 전체 추론 파이프라인 — SE → (선택) SR
        t0 = time.perf_counter()
        try:
            cleaned = await self._run_pipeline(
                audio, sr, request.apply_super_resolution
            )
        except ModelLoadError:
            # 로드 단계 실패는 상위에서 503으로 매핑되도록 그대로 전파
            raise
        except Exception as exc:
            # 벤더(clearvoice) 추론 내부 오류를 공통 예외로 정규화
            _LOG.exception("clearvoice 디노이즈 추론 실패")
            raise InferenceError(f"Denoise inference failed: {exc}") from exc
        latency_ms = (time.perf_counter() - t0) * 1000.0
        # 3) 결과 WAV 인코딩 + 메타 계산
        wav_bytes = await asyncio.to_thread(encode_wav_bytes, cleaned, _TARGET_SR)
        out_dur = duration_sec(ensure_mono(cleaned), _TARGET_SR)
        return DenoiseResponse(
            audio_bytes=wav_bytes,
            sample_rate=_TARGET_SR,
            content_type="audio/wav",
            duration_sec=out_dur,
            latency_ms=latency_ms,
            super_resolution_applied=request.apply_super_resolution,
            model=self.name,
        )

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그."""
        return feature in {"denoise", "super_resolution"}

    # ------------------------------------------------------------------
    # 내부 파이프라인
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self, audio: np.ndarray, sr: int, apply_sr: bool
    ) -> np.ndarray:
        """SE(필수) → SR(선택) 순서로 오디오를 처리해 mono 결과 반환."""
        # SE 단계
        se_model = await self._ensure_se()
        cleaned = await asyncio.to_thread(_infer_with_tempfile, se_model, audio, sr)
        if not apply_sr:
            return cleaned
        # SR 단계 — 오류 시 SE 결과만이라도 반환하지 않고 명확히 에러를 내보낸다.
        # (부분 성공을 숨기면 디버깅 어려워지므로 드러내는 편이 낫다.)
        sr_model = await self._ensure_sr()
        upscaled = await asyncio.to_thread(
            _infer_with_tempfile, sr_model, cleaned, _TARGET_SR
        )
        return upscaled

    @classmethod
    async def _ensure_se(cls) -> Any:
        """MossFormer2_SE_48K 인스턴스 싱글톤 로드."""
        if cls._se_instance is not None:
            return cls._se_instance
        if cls._se_lock is None:
            cls._se_lock = asyncio.Lock()
        async with cls._se_lock:
            if cls._se_instance is not None:
                return cls._se_instance
            cls._se_instance = await asyncio.to_thread(
                _build_clearvoice,
                "speech_enhancement",
                "MossFormer2_SE_48K",
                get_mossformer2_se_checkpoint_dir(),
            )
            return cls._se_instance

    @classmethod
    async def _ensure_sr(cls) -> Any:
        """MossFormer2_SR_48K 인스턴스 싱글톤 로드 (선택적)."""
        if cls._sr_instance is not None:
            return cls._sr_instance
        if cls._sr_lock is None:
            cls._sr_lock = asyncio.Lock()
        async with cls._sr_lock:
            if cls._sr_instance is not None:
                return cls._sr_instance
            cls._sr_instance = await asyncio.to_thread(
                _build_clearvoice,
                "speech_super_resolution",
                "MossFormer2_SR_48K",
                get_mossformer2_sr_checkpoint_dir(),
            )
            return cls._sr_instance


def _build_clearvoice(task: str, model_name: str, checkpoint_dir: str) -> Any:
    """ClearVoice 인스턴스 빌드. 실패 시 ModelLoadError로 래핑."""
    # lazy import — 모듈 import 시점에 PyTorch/MPS 초기화되지 않게
    try:
        from clearvoice import ClearVoice
    except ImportError as exc:
        raise ModelLoadError(
            "clearvoice 라이브러리가 설치되어 있지 않음. "
            "`uv sync` 실행 후 다시 시도하세요.",
        ) from exc
    # 체크포인트 폴더 실존 검사 — clearvoice가 없으면 HF에서 자동 다운로드하지만
    # 네트워크 의존성을 드러내기 위해 명확히 먼저 체크.
    ckpt = Path(checkpoint_dir)
    if not ckpt.exists() or not any(ckpt.iterdir()):
        raise ModelLoadError(
            f"체크포인트 디렉터리가 비어있음: {checkpoint_dir}. "
            "`bash scripts/download_models.sh` 를 실행해 가중치를 내려받으세요.",
        )
    _LOG.info(
        "clearvoice 로드 시작: task=%s, model=%s, ckpt=%s",
        task, model_name, checkpoint_dir,
    )
    try:
        instance = ClearVoice(task=task, model_names=[model_name])
    except Exception as exc:
        raise ModelLoadError(
            f"clearvoice({model_name}) 로드 실패: {exc}",
        ) from exc
    _LOG.info("clearvoice 로드 완료: %s", model_name)
    return instance


def _infer_with_tempfile(
    cv_instance: Any, audio: np.ndarray, sr: int
) -> np.ndarray:
    """임시 WAV 파일로 스풀 후 clearvoice 추론. 결과는 ensure_mono로 1D 정규화."""
    mono = ensure_mono(audio)
    # 16-bit PCM으로 스풀 (clearvoice 내부 soundfile 로더도 float32로 다시 읽음)
    clipped = np.clip(mono, -1.0, 1.0).astype(np.float32, copy=False)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    # 임시 파일은 함수 종료 후 자동 삭제
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        wavfile.write(tmp.name, sr, pcm16)
        tmp.flush()
        result = cv_instance(tmp.name)
    # clearvoice 단일 모델 호출은 ndarray 리턴 (세부 형상은 버전 의존)
    if not isinstance(result, np.ndarray):
        raise InferenceError(
            f"clearvoice 반환 타입이 예상과 다름: {type(result)}",
        )
    return ensure_mono(result.astype(np.float32, copy=False))
