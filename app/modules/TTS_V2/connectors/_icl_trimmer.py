"""TTS V2 — ICL 모드 레퍼런스 꼬리 트리밍 유틸리티.

Qwen3-TTS ICL 모드 합성 결과에 ref_text 끝부분이 오디오 앞에 붙는 문제를
mlx_whisper 단어 수준 타임스탬프를 이용해 제거한다.
이 모듈은 순수 함수만 포함하며 부작용이 없다.
"""
from __future__ import annotations

import numpy as np

from common.logging import get_logger
from app.modules.TTS_V2.connectors._qc_utils import ensure_float32_mono, resample_to_16k
from app.modules.TTS_V2.connectors.whisperx_qc import _MODEL_REPO_MAP

_LOG = get_logger(__name__)

# 트림 시작 지점에 추가하는 여유 시간 (초) — 자연스러운 시작을 위해 앞쪽을 조금 남긴다
_MARGIN_SEC: float = 0.05
# 한국어 기본 발화 속도 (글자/초) — heuristic 폴백에서 expected_text 길이 추정에 사용
_KO_CPS_DEFAULT: float = 6.0


def _resolve_model_repo(model_size: str) -> str:
    """모델 크기 키를 HF 레포 이름으로 변환한다. 알 수 없으면 turbo 로 폴백한다."""
    return _MODEL_REPO_MAP.get(model_size, _MODEL_REPO_MAP["large-v3-turbo"])


def _transcribe_with_words(
    audio_np: np.ndarray,
    sample_rate: int,
    model_repo: str,
) -> list[dict]:
    """mlx_whisper 로 단어 수준 타임스탬프를 추출한다.

    실패 시 빈 리스트를 반환해 호출자가 폴백 경로로 이동하도록 한다.
    """
    try:
        import mlx_whisper
    except ImportError:
        _LOG.warning("mlx_whisper 미설치 — ICL 트리밍 불가, 원본 반환")
        return []
    audio_f32 = ensure_float32_mono(audio_np)
    audio_f32 = resample_to_16k(audio_f32, sample_rate)
    try:
        result: dict = mlx_whisper.transcribe(
            audio_f32,
            path_or_hf_repo=model_repo,
            language="ko",
            word_timestamps=True,
            verbose=None,
        )
    except Exception as exc:
        _LOG.warning("mlx_whisper 전사 실패 — ICL 트리밍 건너뜀: %s", exc)
        return []
    word_segs: list[dict] = []
    for seg in result.get("segments", []):
        word_segs.extend(seg.get("words", []))
    return word_segs


def _find_target_start_sec(
    word_segs: list[dict],
    expected_text: str,
) -> float | None:
    """단어 타임스탬프 목록에서 expected_text 첫 단어의 시작 시각을 찾는다.

    정규화 비교(소문자·공백 제거)로 오타·띄어쓰기 차이를 흡수한다.
    """
    if not word_segs or not expected_text:
        return None
    first_word = expected_text.split()[0].strip().lower()
    for entry in word_segs:
        word = entry.get("word", "").strip().lower()
        # 단어 경계 오차 허용: 전사 단어가 expected_text 첫 단어를 포함하면 매칭
        if first_word in word or word in first_word:
            start = entry.get("start")
            if isinstance(start, (int, float)):
                return float(start)
    return None


def _heuristic_start_sec(
    total_samples: int,
    sample_rate: int,
    expected_text: str,
) -> float:
    """단어 탐색 실패 시 텍스트 길이 비율로 트림 시작 지점을 추정한다.

    전체 오디오 길이에서 expected_text 예상 발화 시간을 빼 ref 꼬리 길이를 추정한다.
    """
    total_sec = total_samples / max(sample_rate, 1)
    expected_sec = len(expected_text) / _KO_CPS_DEFAULT
    # ref 꼬리 추정 = 전체 - 타겟 발화량; 음수가 되면 0으로 클램핑
    return max(0.0, total_sec - expected_sec)


def _trim_audio(
    audio_np: np.ndarray,
    sample_rate: int,
    start_sec: float,
) -> np.ndarray:
    """start_sec 지점(여유 구간 포함)부터 오디오를 슬라이싱한다."""
    margin = max(0.0, start_sec - _MARGIN_SEC)
    start_idx = int(margin * sample_rate)
    # 인덱스가 오디오 길이를 벗어나면 원본 반환
    if start_idx >= len(audio_np):
        return audio_np
    return audio_np[start_idx:]


def trim_icl_prefix(
    audio_np: np.ndarray,
    sample_rate: int,
    expected_text: str,
    model_size: str = "large-v3",
) -> tuple[np.ndarray, bool]:
    """ICL 합성 결과에서 ref_text 꼬리 부분을 제거하고 (오디오, 트림여부) 를 반환한다.

    1단계: mlx_whisper 단어 타임스탬프로 expected_text 시작점 탐지
    2단계: 탐지 실패 시 텍스트 길이 비율 heuristic 으로 추정
    3단계: 두 방법 모두 실패하면 원본 반환 (절대 크래시하지 않음)
    """
    if not expected_text:
        return audio_np, False
    model_repo = _resolve_model_repo(model_size)
    # 1단계: 단어 타임스탬프 기반 트리밍
    word_segs = _transcribe_with_words(audio_np, sample_rate, model_repo)
    start_sec = _find_target_start_sec(word_segs, expected_text)
    if start_sec is not None and start_sec > _MARGIN_SEC:
        trimmed = _trim_audio(audio_np, sample_rate, start_sec)
        _LOG.info(
            "ICL 트리밍 (word-timestamp): %.2fs → %.2fs",
            len(audio_np) / max(sample_rate, 1),
            len(trimmed) / max(sample_rate, 1),
        )
        return trimmed, True
    # 2단계: heuristic 폴백
    h_start = _heuristic_start_sec(len(audio_np), sample_rate, expected_text)
    if h_start > _MARGIN_SEC:
        trimmed = _trim_audio(audio_np, sample_rate, h_start)
        _LOG.info(
            "ICL 트리밍 (heuristic): %.2fs → %.2fs",
            len(audio_np) / max(sample_rate, 1),
            len(trimmed) / max(sample_rate, 1),
        )
        return trimmed, True
    # 3단계: 트리밍 불필요 또는 추정 불가 — 원본 반환
    _LOG.debug("ICL 트리밍 미적용 (레퍼런스 꼬리 감지 안 됨 또는 여유 범위 내)")
    return audio_np, False
