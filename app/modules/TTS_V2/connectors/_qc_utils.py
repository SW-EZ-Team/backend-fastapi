"""TTS V2 QC 공통 헬퍼 — whisperx_qc / asr_qc 양쪽에서 재사용한다.

오디오 변환, WER 계산, 반복/속도/묵음 이상 탐지 함수를 모아둔다.
이 파일은 ai_connectors.tts._quality_gate 만 내부 의존성으로 허용한다.
"""
from __future__ import annotations

import numpy as np

from ai_connectors.tts._quality_gate import has_repetitive_speech, normalize_for_compare
from ai_connectors.errors import ModelLoadError
from common.logging import get_logger

logger = get_logger(__name__)

# 반복 탐지: 동일 3-gram 이 2회 이상이면 repetition 판정
_NGRAM_SIZE = 3
# 묵음 판정 진폭 임계값 (절대값)
_SILENCE_AMP_THRESHOLD = 0.01


def strip_ref_prefix(transcript: str, expected_text: str) -> str:
    """ICL 모드 전사에서 expected_text 이전의 레퍼런스 꼬리를 제거한다.

    Qwen3-TTS ICL 모드는 레퍼런스 오디오의 끝부분 + 타겟 텍스트를 이어 합성한다.
    WhisperX/ASR 전사 결과에 레퍼런스 꼬리가 앞에 붙으므로 expected_text 시작점을
    찾아 그 이전을 제거해야 정확한 CER/WER 를 얻는다.
    """
    if not expected_text:
        return transcript
    idx = transcript.find(expected_text)
    if idx >= 0:
        return transcript[idx:]
    # 전체 매칭 실패 시 첫 단어 기준 매칭 시도
    words = expected_text.split()
    if words:
        idx = transcript.find(words[0])
        if idx >= 0:
            return transcript[idx:]
    return transcript


def ensure_float32_mono(audio: np.ndarray) -> np.ndarray:
    """스테레오 배열을 모노로 합산하고 float32 로 캐스팅한다."""
    if audio.ndim == 2:
        # (채널, 샘플) 또는 (샘플, 채널) 형식 모두 지원
        audio = audio.mean(axis=0) if audio.shape[0] <= 8 else audio.mean(axis=1)
    return audio.astype(np.float32)


def resample_to_16k(audio: np.ndarray, orig_sr: int) -> np.ndarray:
    """librosa 를 사용해 16kHz 로 리샘플링한다."""
    if orig_sr == 16000:
        return audio
    try:
        import librosa
        return librosa.resample(audio, orig_sr=orig_sr, target_sr=16000)
    except ImportError as exc:
        raise ModelLoadError("librosa 패키지가 필요합니다.") from exc


def compute_wer(hypothesis: str, reference: str) -> float:
    """jiwer 로 단어 오류율을 계산한다. 실패 시 0.0 반환."""
    try:
        import jiwer
        ref_n = normalize_for_compare(reference)
        hyp_n = normalize_for_compare(hypothesis)
        if not ref_n and not hyp_n:
            return 0.0
        if not ref_n:
            return 1.0
        return float(jiwer.wer(ref_n, hyp_n))
    except Exception as exc:
        logger.warning("WER 계산 실패, 0.0 반환: %s", exc)
        return 0.0


def check_repetition(transcript: str) -> bool:
    """전사 텍스트에서 n-gram 반복을 탐지한다.

    동일한 3-gram 이 2회 이상 등장하면 True 를 반환한다.
    """
    if has_repetitive_speech(transcript):
        return True
    words = transcript.strip().split()
    if len(words) < _NGRAM_SIZE * 2:
        return False
    seen: set[tuple[str, ...]] = set()
    for i in range(len(words) - _NGRAM_SIZE + 1):
        gram = tuple(words[i : i + _NGRAM_SIZE])
        if gram in seen:
            return True
        seen.add(gram)
    return False


def check_speed_anomaly(
    text: str,
    duration_sec: float,
    cps_min: float,
    cps_max: float,
) -> bool:
    """발화 속도가 정상 범위(초당 글자 수)를 벗어났는지 확인한다.

    text 에는 실제 발화된 전사 텍스트를 전달해야 정확한 CPS 를 얻는다.
    ICL 모드에서 레퍼런스 꼬리가 포함된 경우에도 전사 전체가 발화량이다.
    """
    if duration_sec <= 0:
        return True
    char_count = len(normalize_for_compare(text))
    cps = char_count / duration_sec
    return cps < cps_min or cps > cps_max


def check_excessive_silence(audio_np: np.ndarray, max_ratio: float) -> bool:
    """묵음 구간 비율이 허용 상한을 초과하는지 확인한다."""
    if len(audio_np) == 0:
        return True
    silent_count = int(np.sum(np.abs(audio_np) < _SILENCE_AMP_THRESHOLD))
    return (silent_count / len(audio_np)) > max_ratio


def determine_qc_reason(
    transcript: str,
    expected_text: str,
    audio_np: np.ndarray,
    duration_sec: float,
    cer: float,
    wer: float,
    cer_threshold: float,
    wer_threshold: float,
    ko_cps_min: float,
    ko_cps_max: float,
    silence_max_ratio: float,
) -> str:
    """QC 판정 이유를 우선순위 순으로 결정한다.

    반환 가능 값: "ok" / "repetition" / "speed_anomaly"
                  / "excessive_silence" / "high_cer" / "high_wer"
    """
    if check_repetition(transcript):
        return "repetition"
    # 속도 판정은 실제 발화량(전사 텍스트)을 기준으로 한다.
    # ICL 모드에서 레퍼런스 꼬리가 포함되어도 전사 전체가 실제 음성이다.
    if check_speed_anomaly(transcript, duration_sec, ko_cps_min, ko_cps_max):
        return "speed_anomaly"
    if check_excessive_silence(audio_np, silence_max_ratio):
        return "excessive_silence"
    if cer > cer_threshold:
        return "high_cer"
    if wer > wer_threshold:
        return "high_wer"
    return "ok"
