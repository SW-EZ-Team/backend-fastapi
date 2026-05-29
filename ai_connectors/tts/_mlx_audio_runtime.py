"""mlx-audio Qwen3-TTS 실행 유틸 (커넥터에서 분리).

SRP: 모델 빌드 + 1회 추론 + GenerationResult 수집 로직만 담당.
커넥터 본체(mlx_audio_qwen3_tts_connector.py)는 Protocol 구현과 싱글톤 관리만 하고
실제 mlx-audio 호출은 여기 함수들에 위임한다 — 파일 길이 제한(200줄) 준수.
"""
from __future__ import annotations

import tempfile
from typing import Any

import numpy as np
from scipy.io import wavfile

from common.audio_io import ensure_mono
from common.config import get_qwen3_tts_model_path
from common.logging import get_logger

from ..errors import InferenceError, ModelLoadError

_LOG = get_logger(__name__)

# Qwen3-TTS 모델 기본 sample_rate — load_audio(ref, sample_rate=model.sample_rate)
# 호출이 내부에서 일어나므로 우리가 먼저 리샘플링하지 않아도 되지만, 32kHz 이상
# 레퍼런스는 모델이 기대하는 레이트와 달라 느려지므로 기본 24kHz 로 맞춰 스풀한다.
_TARGET_SR = 24000


def build_model() -> Any:
    """mlx_audio.tts.utils.load 로 모델 빌드. 실패 시 ModelLoadError 로 래핑."""
    # lazy import — 모듈 import 시점에 MLX 디바이스 초기화 지연
    try:
        from mlx_audio.tts.utils import load
    except ImportError as exc:
        raise ModelLoadError(
            "mlx-audio 라이브러리가 설치되어 있지 않음. "
            "`uv sync` 로 pyproject 의존성을 설치하세요.",
        ) from exc
    model_path = get_qwen3_tts_model_path()
    _LOG.info("Qwen3-TTS 모델 로드 시작: %s", model_path)
    try:
        model = load(model_path)
    except Exception as exc:
        # 로드 실패 원인은 다양 — bf16 역직렬화, HF 다운로드 실패, 캐시 경로 오타 등.
        # 사용자에게 구체 원인은 메시지로 드러내되 타입은 ModelLoadError 로 통일.
        raise ModelLoadError(
            f"Qwen3-TTS 모델 생성 실패 (path={model_path}): {exc}",
        ) from exc
    _LOG.info("Qwen3-TTS 모델 로드 완료")
    return model


def run_generate(
    model: Any,
    text: str,
    ref_audio: np.ndarray,
    ref_sr: int,
    ref_text: str | None,
    language: str,
    speed: float,
    temperature: float = 0.9,
    top_k: int = 50,
    top_p: float = 1.0,
    repetition_penalty: float = 1.05,
) -> tuple[np.ndarray, int]:
    """tempfile 경유 Qwen3-TTS.generate 호출 → (mono float32 numpy, sample_rate).

    mlx-audio 의 load_audio 는 str 경로 또는 mx.array 만 받으므로, 바이트로 들어온
    레퍼런스는 임시 WAV 로 스풀해서 넘긴다. scipy.io.wavfile 쓰는 방식은
    clearvoice 커넥터와 동일한 패턴.

    ref_text 가 None 이면 model.generate 에서 x_vector_only_mode=True 로 진입한다.
    이 경우 화자 유사도가 0.89 → 0.75 수준으로 저하된다.
    temperature/top_k/top_p/repetition_penalty 는 외부에서 주입해 A/B 튜닝 가능.
    """
    # float32 mono 를 16-bit PCM 으로 스풀
    mono = ensure_mono(ref_audio)
    clipped = np.clip(mono, -1.0, 1.0).astype(np.float32, copy=False)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    # ref_text 없으면 x_vector_only_mode — model.generate 에 None 전달로 분기
    use_x_vector_only = ref_text is None or not ref_text.strip()
    # 임시 파일은 with 블록 종료 시 자동 삭제 (mlx-audio 내부에서 파일을 모두 읽고 빠짐)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        wavfile.write(tmp.name, ref_sr, pcm16)
        tmp.flush()
        # 스트리밍 OFF — ICL 모드에서는 단일 GenerationResult 가 yield 되는 것을 확인
        # (qwen3_tts._generate_icl 의 non-streaming 분기 기준).
        # 긴 텍스트가 split_pattern 으로 여러 세그먼트일 수 있으나 ICL 은 단일 세그먼트.
        chunks: list[Any] = []
        generate_kwargs: dict[str, Any] = {
            "text": text,
            "ref_audio": tmp.name,
            "lang_code": language,
            "speed": speed,
            "stream": False,
            "verbose": False,
            "temperature": temperature,
            "top_k": top_k,
            "top_p": top_p,
            "repetition_penalty": repetition_penalty,
        }
        if use_x_vector_only:
            # ref_text 없음 — x_vector_only 모드로 화자 벡터만 참조
            generate_kwargs["x_vector_only_mode"] = True
        else:
            generate_kwargs["ref_text"] = ref_text
        for result in model.generate(**generate_kwargs):
            chunks.append(result)
    if not chunks:
        raise InferenceError("Qwen3-TTS 가 빈 GenerationResult 를 반환함")
    return _collect_audio(chunks, _resolve_sample_rate(model, chunks))


def _collect_audio(chunks: list[Any], sample_rate: int) -> tuple[np.ndarray, int]:
    """GenerationResult 리스트를 (float32 mono numpy, sample_rate) 로 합친다.

    GenerationResult.audio 는 mx.array 1D (mono). 여러 chunk 면 순서대로 concat.
    mx.array → numpy 변환은 np.asarray 한 번이면 된다(MLX 공식 변환 경로).
    """
    arrays: list[np.ndarray] = []
    for result in chunks:
        audio_mx = getattr(result, "audio", None)
        if audio_mx is None:
            continue
        arrays.append(np.asarray(audio_mx, dtype=np.float32))
    if not arrays:
        raise InferenceError("Qwen3-TTS 결과에 audio 필드가 비어있음")
    audio_np = np.concatenate(arrays) if len(arrays) > 1 else arrays[0]
    # 방어적으로 1D mono 보장
    return ensure_mono(audio_np), sample_rate


def _resolve_sample_rate(model: Any, chunks: list[Any]) -> int:
    """출력 샘플레이트 결정: 첫 chunk 의 sample_rate 우선, 없으면 model.sample_rate."""
    first = chunks[0]
    sr = getattr(first, "sample_rate", None)
    if isinstance(sr, int) and sr > 0:
        return sr
    # 모델 property fallback — Qwen3-TTS 는 config.sample_rate(기본 24000) 사용
    model_sr = getattr(model, "sample_rate", None)
    if isinstance(model_sr, int) and model_sr > 0:
        return model_sr
    return _TARGET_SR
