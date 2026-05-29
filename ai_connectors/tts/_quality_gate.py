"""TTS 품질 게이트용 텍스트 비교 유틸.

화자 유사도만 높은데 내용이 다른 출력을 막기 위해
ASR round-trip 결과를 문자 단위로 비교한다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_PUNCT_RE = re.compile(r"[^\w가-힣]+", re.UNICODE)
_WORD_RE = re.compile(r"[\w가-힣]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class TTSQualityResult:
    """ASR round-trip 판정 결과."""

    passed: bool
    cer: float
    threshold: float
    transcript: str
    reason: str = "ok"


def choose_cer_threshold(text: str) -> float:
    """텍스트 길이에 따라 허용 CER 임계값을 정한다."""
    length = len(normalize_for_compare(text))
    if length < 40:
        return 0.35
    if length < 120:
        return 0.22
    return 0.15


def evaluate_roundtrip(target_text: str, transcript: str) -> TTSQualityResult:
    """목표 텍스트와 ASR round-trip 결과를 비교해 통과 여부를 계산한다."""
    threshold = choose_cer_threshold(target_text)
    cer = compute_cer(transcript, target_text)
    reason = determine_quality_reason(target_text, transcript, cer, threshold)
    return TTSQualityResult(
        passed=reason == "ok",
        cer=cer,
        threshold=threshold,
        transcript=transcript.strip(),
        reason=reason,
    )


def determine_quality_reason(
    target_text: str,
    transcript: str,
    cer: float,
    threshold: float,
) -> str:
    """반복/환각/내용 불일치 중 품질 실패 이유를 결정한다."""
    if has_repetitive_speech(transcript):
        return "repetition"
    if has_hallucinated_extra(target_text, transcript):
        return "hallucinated_extra"
    if cer > threshold:
        return "high_cer"
    return "ok"


def has_repetitive_speech(text: str) -> bool:
    """전사 텍스트에서 같은 말 반복 붕괴를 탐지한다."""
    return _has_repeated_word_ngram(text) or _has_repeated_char_span(text)


def has_hallucinated_extra(target_text: str, transcript: str) -> bool:
    """목표 문장을 말한 뒤 불필요한 말을 길게 덧붙인 경우를 탐지한다."""
    target = normalize_for_compare(target_text)
    spoken = normalize_for_compare(transcript)
    if not target or not spoken:
        return False
    return target in spoken and len(spoken) > int(len(target) * 1.35)


def is_ref_text_mismatch(provided_text: str, asr_text: str) -> bool:
    """클라이언트 제공 ref_text 와 실제 ref_audio ASR 결과의 불일치를 판정한다."""
    if not provided_text.strip() or not asr_text.strip():
        return False
    cer = compute_cer(provided_text, asr_text)
    return cer > 0.28


def compute_cer(predicted: str, expected: str) -> float:
    """NFKC 정규화 후 문자 단위 CER 를 계산한다."""
    left = normalize_for_compare(predicted)
    right = normalize_for_compare(expected)
    if not left and not right:
        return 0.0
    return _levenshtein(left, right) / max(len(right), 1)


def normalize_for_compare(text: str) -> str:
    """품질 비교용 정규화.

    구두점과 공백 차이 때문에 품질 게이트가 과민반응하지 않도록
    한글/영문/숫자만 남기고 비교한다.
    """
    normalized = unicodedata.normalize("NFKC", text).strip().lower()
    return _PUNCT_RE.sub("", normalized)


def _has_repeated_word_ngram(text: str) -> bool:
    """공백 단어 기준 반복 n-gram 을 탐지한다."""
    words = [m.group(0).lower() for m in _WORD_RE.finditer(text)]
    if len(words) < 4:
        return False
    max_size = min(5, len(words) // 2)
    for size in range(2, max_size + 1):
        for start in range(0, len(words) - size * 2 + 1):
            left = words[start : start + size]
            right = words[start + size : start + size * 2]
            if left == right:
                return True
    return False


def _has_repeated_char_span(text: str) -> bool:
    """띄어쓰기가 흔들리는 전사에서 연속 문자 반복을 탐지한다."""
    compact = normalize_for_compare(text)
    if len(compact) < 12:
        return False
    max_size = min(24, len(compact) // 2)
    for size in range(5, max_size + 1):
        for start in range(0, len(compact) - size * 2 + 1):
            span = compact[start : start + size]
            if len(set(span)) <= 2:
                continue
            if span == compact[start + size : start + size * 2]:
                return True
    return False


def _levenshtein(left: str, right: str) -> int:
    """문자열 두 개의 Levenshtein 거리를 계산한다."""
    if not left:
        return len(right)
    if not right:
        return len(left)
    prev = list(range(len(right) + 1))
    curr = [0] * (len(right) + 1)
    for i, left_char in enumerate(left, start=1):
        curr[0] = i
        for j, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost,
            )
        prev, curr = curr, [0] * (len(right) + 1)
    return prev[-1]
