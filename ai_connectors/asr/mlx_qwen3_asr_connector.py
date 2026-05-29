"""로컬 Mac용 Qwen3-ASR (MLX) 커넥터.

mlx-qwen3-asr 라이브러리 (https://github.com/moona3k/mlx-qwen3-asr)를 얇게 감싼다.
Protocol 인터페이스 준수 + 싱글톤 lazy load + 오디오 정규화까지 담당한다.

[MLX 스레드 안전성]
MLX Metal 커맨드 버퍼는 스레드 어파인(thread-affine)이다.
asyncio.to_thread()는 기본 스레드풀에서 임의 스레드를 할당하므로
첫 번째 호출(로드)과 두 번째 호출(추론)이 서로 다른 OS 스레드에
배정될 경우 Metal GPU assertion 크래시가 발생한다.
이를 막기 위해 max_workers=1 전용 ThreadPoolExecutor를 클래스 레벨에서
고정 보유한다. 로드와 추론 모두 동일 스레드에서 직렬 실행된다.
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from common.audio_io import duration_sec, load_audio_from_bytes
from common.config import get_qwen3_asr_model_path
from common.logging import get_logger

from ..errors import InferenceError, ModelLoadError
from ..schemas import ASRRequest, ASRResponse

_LOG = get_logger(__name__)

# ASR 타깃 샘플레이트 — Qwen3-ASR는 16kHz mono 입력을 요구
_TARGET_SR = 16000


class MLXQwen3ASRConnector:
    """Qwen3-ASR 1.7B bf16 원본을 MLX로 실행하는 커넥터.

    클래스 레벨 싱글톤이라 프로세스당 한 번만 모델을 로드한다.
    MLX Metal 스레드 어파인 특성 때문에 전용 단일 스레드 executor를 사용한다.
    """

    # 커넥터 식별자 — registry 키와 동일하게 유지
    name: str = "mlx-qwen3-asr"

    # MLX 세션 싱글톤. 타입은 mlx_qwen3_asr.Session
    _session: Any | None = None

    # MLX 전용 단일 스레드 executor — 모든 Metal 연산이 같은 OS 스레드에서 실행됨
    # max_workers=1 로 고정해 스레드 어파인 보장
    _mlx_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=1)

    # 세션 로드 직렬화 락 — 이벤트 루프 바인딩 시점에 생성
    _load_lock: asyncio.Lock | None = None

    async def generate(self, request: ASRRequest) -> ASRResponse:
        """ASR 요청 → 트랜스크립트 응답.

        오디오 바이트를 16kHz mono numpy로 변환한 뒤 Session.transcribe 호출.
        오디오 IO는 일반 스레드풀, MLX 추론은 전용 단일 스레드 executor 사용.
        """
        # 1) 오디오 로드 + 정규화 — 일반 asyncio 스레드풀 사용 (Metal 무관 IO)
        audio, sr = await asyncio.to_thread(
            load_audio_from_bytes, request.audio_bytes, _TARGET_SR
        )
        audio_len = duration_sec(audio, sr)

        # 2) 세션 준비 (최초 1회만, MLX 전용 스레드에서 로드)
        session = await self._ensure_session()

        # 3) 실제 추론 — MLX 전용 단일 스레드 executor로 제한
        # 세션 로드와 동일한 스레드에서 실행해 Metal 어파인 조건 충족
        loop = asyncio.get_running_loop()
        t0 = time.perf_counter()
        try:
            result = await loop.run_in_executor(
                self.__class__._mlx_executor,
                lambda: session.transcribe(
                    (audio, sr),
                    language=request.language,
                ),
            )
        except Exception as exc:
            # 벤더 SDK(MLX Qwen3-ASR)가 던지는 예외 타입이 공개 문서에 없어
            # 공통 예외 인터페이스(InferenceError)로 정규화한다.
            # 이 패턴은 errors.py의 설계 원칙("벤더 예외 → 공통형 번역") 그대로다.
            _LOG.exception("mlx-qwen3-asr 추론 실패")
            raise InferenceError(f"ASR inference failed: {exc}") from exc
        latency_ms = (time.perf_counter() - t0) * 1000.0

        # 4) 응답 스키마로 정규화
        return ASRResponse(
            text=getattr(result, "text", "") or "",
            language=getattr(result, "language", request.language) or request.language,
            duration_sec=audio_len,
            latency_ms=latency_ms,
            model=self.name,
        )

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그. 현재는 transcription만."""
        return feature in {"transcription", "language_hint"}

    @classmethod
    async def _ensure_session(cls) -> Any:
        """세션 싱글톤 생성 — 동시 접근은 Lock으로 직렬화한다.

        세션 로드도 _mlx_executor 전용 스레드에서 실행 — 나중에 transcribe가
        같은 스레드에 배정되도록 Metal 어파인 일관성을 처음부터 맞춘다.
        """
        # 빠른 경로 — 이미 로드됐으면 락 없이 반환
        if cls._session is not None:
            return cls._session

        # Lock 지연 생성 — 현재 이벤트 루프에 바인딩
        if cls._load_lock is None:
            cls._load_lock = asyncio.Lock()

        async with cls._load_lock:
            # 락 획득 후 재확인 — 대기 중에 다른 요청이 로드했을 수 있음
            if cls._session is not None:
                return cls._session
            loop = asyncio.get_running_loop()
            # 로드도 MLX 전용 executor 스레드에서 실행 — 추론과 동일 스레드 보장
            cls._session = await loop.run_in_executor(
                cls._mlx_executor, cls._build_session
            )
            return cls._session

    @classmethod
    def _build_session(cls) -> Any:
        """mlx_qwen3_asr.Session 생성. 실패 시 ModelLoadError로 래핑."""
        # lazy import — 모듈 import 시점에 MLX 디바이스 초기화가 일어나지 않도록
        try:
            from mlx_qwen3_asr import Session
        except ImportError as exc:
            raise ModelLoadError(
                "mlx-qwen3-asr 라이브러리가 설치되어 있지 않음. "
                "`uv pip install git+https://github.com/moona3k/mlx-qwen3-asr.git` 실행 필요"
            ) from exc
        model_path = get_qwen3_asr_model_path()
        _LOG.info("Qwen3-ASR 세션 로드 시작: %s", model_path)
        try:
            session = Session(model=model_path)
        except Exception as exc:
            # 로드 실패 원인은 다양 — bf16 역직렬화, 디스크 경로, HF 다운로드 실패 등.
            # 사용자에게 구체 원인을 메시지로 전달하되 타입은 ModelLoadError로 통일한다.
            raise ModelLoadError(
                f"Qwen3-ASR 세션 생성 실패 (path={model_path}): {exc}"
            ) from exc
        _LOG.info("Qwen3-ASR 세션 로드 완료")
        return session
