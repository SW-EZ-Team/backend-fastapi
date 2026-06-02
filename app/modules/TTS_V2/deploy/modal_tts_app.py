"""Modal GPU용 Qwen3-TTS 보이스 클로닝 서버."""
from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import time
from typing import Annotated, Protocol

import modal
import numpy as np
from fastapi import File, Form, Header, HTTPException, UploadFile
from numpy.typing import NDArray
from starlette.responses import Response

from app.modules.TTS_V2.deploy.modal_tts_utils import (
    SynthesisMeta,
    encode_wav,
    normalize_language,
    response_headers,
)

APP_NAME = os.environ.get("QWEN3_TTS_MODAL_APP_NAME", "qwen3-tts-modal")
MODEL_ID = os.environ.get("QWEN3_TTS_MODAL_MODEL_ID", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
GPU = os.environ.get("QWEN3_TTS_MODAL_GPU", "H100:1")
AUTH_TOKEN = os.environ.get("QWEN3_TTS_MODAL_TOKEN", "").strip()
DEFAULT_POOL_SIZE = 6
MINUTES = 60


def _env_int_clamped(key: str, default: int, min_value: int, max_value: int) -> int:
    """잘못된 정수 환경값은 import 실패 대신 기본값으로 복구한다."""
    raw_value = os.environ.get(key, str(default))
    try:
        value = int(raw_value)
    except ValueError:
        value = default
    return max(min_value, min(max_value, value))


POOL_SIZE = _env_int_clamped("QWEN3_TTS_MODAL_POOL_SIZE", DEFAULT_POOL_SIZE, 1, 16)


class VoiceCloneModel(Protocol):
    """Qwen3TTSModel의 보이스 클로닝 호출면만 정의한다."""

    def generate_voice_clone(
        self,
        text: str,
        language: str,
        ref_audio: str,
        ref_text: str | None = None,
        x_vector_only_mode: bool = False,
        speed: float = 1.0,
    ) -> tuple[list[NDArray[np.float32]], int]:
        """레퍼런스 화자로 입력 텍스트를 합성한다."""


app = modal.App(APP_NAME)
hf_cache = modal.Volume.from_name(f"{APP_NAME}-hf-cache", create_if_missing=True)

image = (
    modal.Image.from_registry("nvidia/cuda:12.8.1-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .apt_install("ffmpeg", "libsndfile1", "sox")
    .uv_pip_install(
        "fastapi[standard]==0.116.1",
        "huggingface-hub[hf-transfer]==0.36.2",
        "numpy==2.4.0",
        "qwen-tts==0.1.1",
        "soundfile==0.13.1",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "QWEN3_TTS_MODAL_MODEL_ID": MODEL_ID,
        }
    )
    .add_local_python_source("app.modules.TTS_V2.deploy.modal_tts_utils")
)

secrets = (
    [modal.Secret.from_dict({"QWEN3_TTS_MODAL_TOKEN": AUTH_TOKEN})]
    if AUTH_TOKEN
    else []
)


@app.cls(
    image=image,
    gpu=GPU,
    volumes={"/root/.cache/huggingface": hf_cache},
    timeout=30 * MINUTES,
    scaledown_window=int(os.environ.get("QWEN3_TTS_MODAL_SCALEDOWN_SEC", "30")),
    secrets=secrets,
)
@modal.concurrent(max_inputs=POOL_SIZE)
class Qwen3TTSServer:
    """Qwen3-TTS 1.7B Base를 로드해 clone TTS를 제공한다."""

    model_pool: asyncio.Queue[VoiceCloneModel]
    pool_size: int

    @modal.enter()
    def load(self) -> None:
        """컨테이너 시작 시 독립 모델 인스턴스 풀을 로드한다."""
        import torch
        from qwen_tts import Qwen3TTSModel

        print(f"[qwen3-tts] 콜드스타트: gpu={GPU}, pool_size={POOL_SIZE}, model={MODEL_ID}")
        self.pool_size = POOL_SIZE
        self.model_pool = asyncio.Queue(maxsize=POOL_SIZE)
        for index in range(POOL_SIZE):
            model = Qwen3TTSModel.from_pretrained(
                MODEL_ID,
                device_map="cuda:0",
                dtype=torch.bfloat16,
                attn_implementation=os.environ.get("QWEN3_TTS_ATTN", "sdpa"),
            )
            self.model_pool.put_nowait(model)
            print(f"[qwen3-tts] 모델 인스턴스 로드 완료: {index + 1}/{POOL_SIZE}")

    @modal.method()
    def healthz(self) -> dict[str, str | int]:
        """원격 호출용 헬스체크다."""
        return {
            "status": "ok",
            "model": MODEL_ID,
            "gpu": GPU,
            "pool_size": getattr(self, "pool_size", POOL_SIZE),
        }

    @modal.method()
    async def synthesize_remote(
        self,
        text: str,
        ref_audio_b64: str,
        ref_text: str | None = None,
        language: str = "Korean",
        speed: float = 1.0,
    ) -> dict[str, str | int | float | bool]:
        """base64 레퍼런스를 받아 base64 WAV로 반환하는 원격 메서드다."""
        ref_audio = base64.b64decode(ref_audio_b64)
        wav_bytes, meta = await self._synthesize(text, ref_audio, ref_text, language, speed)
        return {
            "audio_b64": base64.b64encode(wav_bytes).decode("ascii"),
            "sample_rate": meta.sample_rate,
            "duration_sec": meta.duration_sec,
            "latency_ms": meta.latency_ms,
            "char_count": len(text),
            "model": MODEL_ID,
            "ref_text_used": meta.ref_text_used,
            "x_vector_only": meta.x_vector_only,
        }

    @modal.fastapi_endpoint(method="POST", docs=True)
    async def synthesize(
        self,
        text: Annotated[str, Form()],
        ref_audio: Annotated[UploadFile, File()],
        ref_text: Annotated[str | None, Form()] = None,
        language: Annotated[str, Form()] = "Korean",
        speed: Annotated[float, Form()] = 1.0,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        """기존 FastAPI 커넥터가 호출하는 multipart HTTP 엔드포인트다."""
        self._verify_token(authorization)
        ref_audio_bytes = await ref_audio.read()
        wav_bytes, meta = await self._synthesize(
            text=text,
            ref_audio_bytes=ref_audio_bytes,
            ref_text=ref_text,
            language=language,
            speed=speed,
        )
        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers=response_headers(meta, text),
        )

    def _verify_token(self, authorization: str | None) -> None:
        """토큰이 배포 환경에 주입된 경우 Bearer 인증을 강제한다."""
        expected = os.environ.get("QWEN3_TTS_MODAL_TOKEN", "").strip()
        if expected and authorization != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="invalid token")

    async def _synthesize(
        self,
        text: str,
        ref_audio_bytes: bytes,
        ref_text: str | None,
        language: str,
        speed: float,
    ) -> tuple[bytes, "SynthesisMeta"]:
        """업로드 오디오를 임시 파일로 넘긴 뒤 Qwen3-TTS를 호출한다."""
        started_at = time.perf_counter()
        clean_ref_text = ref_text.strip() if ref_text else ""
        use_x_vector_only = not clean_ref_text
        model = await self._acquire_model()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            tmp.write(ref_audio_bytes)
            tmp.flush()
            try:
                wavs, sample_rate = await asyncio.to_thread(
                    model.generate_voice_clone,
                    text=text,
                    language=normalize_language(language),
                    ref_audio=tmp.name,
                    ref_text=clean_ref_text or None,
                    x_vector_only_mode=use_x_vector_only,
                    speed=max(0.5, min(2.0, speed)),
                )
            finally:
                self._release_model(model)
        wav_bytes = encode_wav(wavs[0], sample_rate)
        return wav_bytes, SynthesisMeta(
            sample_rate=sample_rate,
            duration_sec=float(len(wavs[0])) / float(sample_rate),
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            ref_text_used=clean_ref_text,
            x_vector_only=use_x_vector_only,
        )

    async def _acquire_model(self) -> VoiceCloneModel:
        """풀이 준비되지 않은 상태는 503으로 알려 호출자가 재시도하게 한다."""
        pool = getattr(self, "model_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="모델 풀이 아직 준비되지 않았다.")
        return await pool.get()

    def _release_model(self, model: VoiceCloneModel) -> None:
        """예외가 나도 모델 인스턴스를 풀로 되돌린다."""
        self.model_pool.put_nowait(model)
