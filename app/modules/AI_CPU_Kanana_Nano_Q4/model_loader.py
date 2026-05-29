"""Llama 싱글톤 로더. Celery 워커 프로세스당 1회만 로드한다."""
import os
import threading
from pathlib import Path

from llama_cpp import Llama

from .config import CONTEXT_SIZE, N_GPU_LAYERS, THREADS

# 환경변수로 모델 경로를 재지정할 수 있도록 상수 분리
_MODEL_PATH_ENV = "KANANA_MODEL_PATH"
_DEFAULT_MODEL = (
    Path(__file__).parent / "models" / "kanana-nano-2.1b-instruct.Q4_K_M.gguf"
)

# 스레드 안전 싱글톤 구현 — double-checked locking 패턴
# dict 홀더로 싱글톤 관리 — global 문 없이 변경 가능
_lock = threading.Lock()
_STATE: dict[str, Llama | None] = {"llm": None}


def get_llama() -> Llama:
    """싱글톤 Llama 인스턴스를 반환한다. 최초 호출 시 1.3GB 모델 로드."""
    # 첫 번째 확인: 락 없이 빠르게 체크 (이미 로드된 경우 즉시 반환)
    if _STATE["llm"] is not None:
        return _STATE["llm"]
    with _lock:
        # 두 번째 확인: 락 획득 후 재확인 (경쟁 조건 방지)
        if _STATE["llm"] is not None:
            return _STATE["llm"]
        model_path = os.environ.get(_MODEL_PATH_ENV, str(_DEFAULT_MODEL))
        if not Path(model_path).is_file():
            raise FileNotFoundError(
                f"Kanana 모델 파일을 찾을 수 없음: {model_path}. "
                f"{_MODEL_PATH_ENV} 환경변수로 경로를 지정하거나 scripts/setup.sh 실행."
            )
        _STATE["llm"] = Llama(
            model_path=model_path,
            n_ctx=CONTEXT_SIZE,
            n_threads=THREADS,
            n_gpu_layers=N_GPU_LAYERS,
            verbose=False,
        )
        return _STATE["llm"]
