"""TTS V2 파이프라인 설정값 — 청크·재시도·QC·후처리·서버 파라미터.

모든 값은 환경변수로 override 가능하다.
이 파일은 os 와 logging 만 import 한다 (순환 import 방지).
"""
from __future__ import annotations

import logging
import os

_LOG = logging.getLogger(__name__)


def _safe_int(key: str, default: int) -> int:
    """환경변수를 int 로 안전하게 읽는다.

    값이 없거나 숫자로 변환 불가 시 default 를 반환하고 경고 로그를 남긴다.
    """
    raw = os.getenv(key, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        _LOG.warning("환경변수 %s 파싱 실패 (%r) — 기본값 %d 사용", key, raw, default)
        return default


def _safe_float(key: str, default: float) -> float:
    """환경변수를 float 로 안전하게 읽는다.

    값이 없거나 숫자로 변환 불가 시 default 를 반환하고 경고 로그를 남긴다.
    """
    raw = os.getenv(key, "")
    if not raw:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        _LOG.warning("환경변수 %s 파싱 실패 (%r) — 기본값 %f 사용", key, raw, default)
        return default


# ─── 청크 설정 ────────────────────────────────────────────────────────────
# 청크 최소 글자 수 — 너무 짧으면 TTS 엔진이 불자연스러운 묵음을 삽입한다
TTS_V2_CHUNK_MIN_CHARS: int = _safe_int("TTS_V2_CHUNK_MIN_CHARS", 40)
# 청크 최대 글자 수 — 초과하면 합성 시간이 길어지고 QC 정확도가 떨어진다
TTS_V2_CHUNK_MAX_CHARS: int = _safe_int("TTS_V2_CHUNK_MAX_CHARS", 120)

# ─── 재시도 설정 ──────────────────────────────────────────────────────────
# QC 실패 시 해당 청크를 재합성하는 최대 횟수
TTS_V2_MAX_RETRIES: int = _safe_int("TTS_V2_MAX_RETRIES", 3)

# ─── QC 임계값 ───────────────────────────────────────────────────────────
# 문자 오류율 허용 상한 — 이 값 초과 시 해당 청크를 재합성한다
TTS_V2_CER_THRESHOLD: float = _safe_float("TTS_V2_CER_THRESHOLD", 0.20)
# 단어 오류율 허용 상한 — CER 보조 지표로 함께 사용한다
TTS_V2_WER_THRESHOLD: float = _safe_float("TTS_V2_WER_THRESHOLD", 0.25)
# 발화 속도 정상 범위 하한 (기대 속도 대비 배율)
TTS_V2_SPEED_MIN_RATIO: float = _safe_float("TTS_V2_SPEED_MIN_RATIO", 0.7)
# 발화 속도 정상 범위 상한 — 초과 시 반복 출력이나 속사로 판정한다
TTS_V2_SPEED_MAX_RATIO: float = _safe_float("TTS_V2_SPEED_MAX_RATIO", 1.5)
# 묵음 구간 비율 상한 — 초과 시 excessive_silence 로 판정한다
TTS_V2_SILENCE_MAX_RATIO: float = _safe_float("TTS_V2_SILENCE_MAX_RATIO", 0.3)

# ─── 오디오 후처리 ────────────────────────────────────────────────────────
# 청크 간 크로스페이드 길이 (ms) — 0이면 하드컷, 50이면 자연스러운 전환
TTS_V2_CROSSFADE_MS: int = _safe_int("TTS_V2_CROSSFADE_MS", 50)
# 목표 loudness (LUFS) — 방송 표준 -16 LUFS 기준
TTS_V2_TARGET_LUFS: float = _safe_float("TTS_V2_TARGET_LUFS", -16.0)
# 피크 제한 (dBFS) — 클리핑 방지를 위해 -2 dBFS 이하로 제한
TTS_V2_PEAK_DBFS: float = _safe_float("TTS_V2_PEAK_DBFS", -2.0)
# 앞뒤 묵음 트림 임계값 (절대 진폭 기준) — 이하이면 묵음으로 간주한다
TTS_V2_TRIM_THRESHOLD: float = _safe_float("TTS_V2_TRIM_THRESHOLD", 0.01)

# ─── QC 엔진 선택 ────────────────────────────────────────────────────────
# "whisperx" / "v1_asr" / "both" — 둘 다 사용하면 더 엄격하지만 느리다
TTS_V2_QC_ENGINE: str = os.getenv("TTS_V2_QC_ENGINE", "whisperx")
# WhisperX 모델 크기 — large-v3 가 정확도 최고, tiny 는 속도 최고
TTS_V2_WHISPERX_MODEL: str = os.getenv("TTS_V2_WHISPERX_MODEL", "large-v3")

# ─── LLM 플래너 ──────────────────────────────────────────────────────────
# 낭독 계획 생성에 사용할 MLX 모델 경로 — Qwen3-4B-Instruct 4bit 양자화, Mac MPS 로컬 실행용
TTS_V2_LLM_PLANNER_MODEL_PATH: str = os.getenv(
    "TTS_V2_LLM_PLANNER_MODEL_PATH",
    "mlx-community/Qwen3-4B-Instruct-2507-4bit",
)

# ─── 서버 ────────────────────────────────────────────────────────────────
# uvicorn 리스닝 포트 — 기본 8010 (8000 은 기존 ASR 서버와 충돌 방지)
TTS_V2_PORT: int = _safe_int("TTS_V2_PORT", 8010)

# ─── 메모리 관리 ─────────────────────────────────────────────────────────
# True 이면 각 노드 실행 후 즉시 모델을 언로드한다 (VRAM 부족 시 사용)
TTS_V2_AGGRESSIVE_UNLOAD: bool = (
    os.getenv("TTS_V2_AGGRESSIVE_UNLOAD", "false").lower() == "true"
)

# ─── 한국어 발화 속도 기준 ───────────────────────────────────────────────
# 정상 발화 속도 범위 (초당 글자 수) — 범위 이탈 시 speed_anomaly 로 판정
TTS_V2_KO_CHARS_PER_SEC_MIN: float = _safe_float("TTS_V2_KO_CHARS_PER_SEC_MIN", 3.0)
TTS_V2_KO_CHARS_PER_SEC_MAX: float = _safe_float("TTS_V2_KO_CHARS_PER_SEC_MAX", 10.0)
