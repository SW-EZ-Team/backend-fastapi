"""로컬 Mac용 Whisper Large V3 Turbo (MLX) 커넥터.

ml-explore/mlx-examples 의 mlx-whisper 패키지(https://github.com/ml-explore/mlx-examples/tree/main/whisper)를
얇게 감싼다. Qwen3-ASR 커넥터(mlx_qwen3_asr_connector.py)와 동일한
Protocol 시그니처 + 싱글톤 lazy load + 오디오 정규화 패턴을 그대로 따른다.

차이점은 mlx-whisper 는 Session 객체가 없는 함수형 API 라는 점이다 —
`mlx_whisper.transcribe(audio, *, path_or_hf_repo=..., **decode_options)` 한 번 호출이
모델 로드와 추론을 모두 처리한다. 따라서 싱글톤으로 보관할 객체는 "한 번이라도
워밍업이 끝났는지" 플래그 + "사용 중인 모델 경로" 한 쌍이다. 실제 모델 가중치는
mlx_whisper 내부 LRU 캐시가 path_or_hf_repo 키로 자동 보관한다.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from common.audio_io import duration_sec, load_audio_from_bytes
from common.config import get_whisper_turbo_model_path
from common.logging import get_logger

from ..errors import InferenceError, ModelLoadError
from ..schemas import ASRRequest, ASRResponse

_LOG = get_logger(__name__)

# Whisper 계열은 16kHz mono 입력을 요구 — Qwen3-ASR 와 동일 규격이므로 audio_io 그대로 재사용
_TARGET_SR = 16000

# language=auto 신호 — mlx_whisper 는 None 일 때 30초 prefix 로 자동 감지함
_AUTO_LANG_TOKEN = "auto"


class MLXWhisperTurboConnector:
    """Whisper Large V3 Turbo(809M) MLX 변환본을 로컬 Mac 에서 실행하는 커넥터.

    mlx-community/whisper-large-v3-turbo (float16, ~3GB) 가 기본 모델이다.
    싱글톤 워밍업은 첫 generate 호출 시 무음 1프레임을 추론에 던져 모델 캐시를
    채우는 방식으로 처리한다 — mlx-whisper 가 함수형 API 라 별도 Session 객체가
    없어 Qwen3-ASR 의 _build_session 과 1:1 대응되는 절차가 없기 때문이다.
    """

    # 커넥터 식별자 — registry 키와 동일하게 유지
    name: str = "mlx-whisper-turbo"

    # 클래스 변수로 싱글톤 보관. 워밍업 완료 시 True 로 전환 — 캐시 자체는 mlx_whisper 모듈이 보관
    _warmed: bool = False
    # Lock 은 첫 호출 시 생성 — 이벤트 루프 바인딩 시점 충돌 방지
    _load_lock: asyncio.Lock | None = None
    # 사용 중 모델 경로 캐시 — 동일 프로세스에서 경로 변경되면 재워밍업 트리거
    _model_path: str | None = None

    async def generate(self, request: ASRRequest) -> ASRResponse:
        """ASR 요청 → 트랜스크립트 응답.

        Qwen3-ASR 커넥터와 동일한 절차: 오디오 정규화 → 워밍업 보장 → 추론 → 응답 매핑.
        """
        # 1) 오디오 로드 + 정규화 (블로킹 IO 는 스레드로)
        audio, sr = await asyncio.to_thread(
            load_audio_from_bytes, request.audio_bytes, _TARGET_SR
        )
        audio_len = duration_sec(audio, sr)
        # 2) 모델 워밍업 보장 (최초 1회만 — 첫 호출에서 모델 로드가 느린 점을 명시화)
        model_path = get_whisper_turbo_model_path()
        await self._ensure_warmed(model_path)
        # 3) 실제 추론 + 지연시간 측정 (MLX 연산도 블로킹)
        t0 = time.perf_counter()
        try:
            result = await asyncio.to_thread(
                self._run_transcribe,
                audio,
                model_path,
                request.language,
            )
        except Exception as exc:
            # mlx-whisper 가 던지는 예외 타입이 공개 문서에 명시되지 않아
            # 공통 예외 인터페이스(InferenceError)로 정규화한다.
            # 이 패턴은 errors.py 의 설계 원칙("벤더 예외 → 공통형 번역") 그대로다.
            _LOG.exception("mlx-whisper-turbo 추론 실패")
            raise InferenceError(f"ASR inference failed: {exc}") from exc
        latency_ms = (time.perf_counter() - t0) * 1000.0
        # 4) 응답 스키마로 정규화 — Qwen3-ASR 응답과 완전 동일 필드 셋
        return ASRResponse(
            text=str(result.get("text", "") or "").strip(),
            language=str(result.get("language") or request.language or "auto"),
            duration_sec=audio_len,
            latency_ms=latency_ms,
            model=self.name,
        )

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그.

        - basic / transcription: 기본 음성→텍스트 변환
        - language_override: 사용자가 ko/en/ja/zh 등 언어 코드 강제 지정 가능
        - language_hint: language_override 의 별칭 — Qwen3-ASR 커넥터와 키 호환 유지
        """
        return feature in {"basic", "transcription", "language_override", "language_hint"}

    @classmethod
    async def _ensure_warmed(cls, model_path: str) -> None:
        """모델 워밍업 보장 — 동시 접근은 Lock 으로 직렬화한다.

        모델 경로가 바뀌었으면(.env 갱신 등) 재워밍업한다. mlx-whisper 가 내부에
        path 별 LRU 캐시를 들고 있으므로 비용은 두 번째 호출 한정이다.
        """
        # 빠른 경로 — 같은 모델로 이미 워밍업했으면 락 없이 반환
        if cls._warmed and cls._model_path == model_path:
            return
        # Lock 지연 생성 — 현재 이벤트 루프에 바인딩
        if cls._load_lock is None:
            cls._load_lock = asyncio.Lock()
        async with cls._load_lock:
            # 락 획득 후 재확인 — 대기 중 다른 요청이 워밍업했을 수 있음
            if cls._warmed and cls._model_path == model_path:
                return
            await asyncio.to_thread(cls._warmup, model_path)
            cls._model_path = model_path
            cls._warmed = True

    @classmethod
    def _warmup(cls, model_path: str) -> None:
        """무음 0.1초 입력으로 모델 가중치를 미리 로드한다.

        mlx-whisper 는 함수형 API 라 첫 transcribe 호출이 곧 모델 로드 시점이다.
        FastAPI 첫 응답이 30초 이상 걸리는 것을 막기 위해 더미 입력으로 미리 채운다.
        실패는 모두 ModelLoadError 로 변환 — 라우터가 503 으로 매핑한다.
        """
        # lazy import — 모듈 import 시점에 MLX 디바이스 초기화가 일어나지 않도록
        try:
            import numpy as np

            import mlx_whisper
        except ImportError as exc:
            raise ModelLoadError(
                "mlx-whisper 라이브러리가 설치되어 있지 않음. "
                "`uv pip install mlx-whisper` 실행 필요"
            ) from exc
        _LOG.info("Whisper Turbo 워밍업 시작: %s", model_path)
        # 0.1초 무음 — 너무 짧으면 mlx-whisper VAD 가 즉시 종료해 일부 가중치만 로드될 수 있어
        # _TARGET_SR * 0.1 = 1600 샘플로 잡는다. float32 영벡터.
        dummy = np.zeros(int(_TARGET_SR * 0.1), dtype=np.float32)
        try:
            mlx_whisper.transcribe(dummy, path_or_hf_repo=model_path)
        except Exception as exc:
            # 로드 실패 원인은 다양 — float16 역직렬화, 디스크 경로, HF 다운로드 실패 등.
            # 사용자에게 구체 원인을 메시지로 전달하되 타입은 ModelLoadError 로 통일한다.
            raise ModelLoadError(
                f"Whisper Turbo 가중치 로드 실패 (path={model_path}): {exc}"
            ) from exc
        _LOG.info("Whisper Turbo 워밍업 완료")

    @classmethod
    def _run_transcribe(
        cls, audio: Any, model_path: str, language: str | None
    ) -> dict[str, Any]:
        """실제 mlx_whisper.transcribe 호출 — 블로킹 함수라 to_thread 에서 실행된다.

        language 가 'auto' 또는 빈 문자열이면 None 으로 변환해 mlx-whisper 의
        30초 prefix 자동 감지에 위임한다. ko/en/ja/zh 같은 ISO 코드는 그대로 통과.
        decode_options 는 키워드 인자로 전달 — language 파라미터가 transcribe 시그니처상
        **decode_options 안으로 들어간다.
        """
        # lazy import — 워밍업 단계에서 import 검증을 끝냈으므로 여기는 단순 재사용
        import mlx_whisper

        decode_options: dict[str, Any] = {}
        if language and language.lower() != _AUTO_LANG_TOKEN:
            decode_options["language"] = language
        # 반환은 dict — generate() 측에서 .get() 으로 안전 추출함
        return mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=model_path,
            **decode_options,
        )
