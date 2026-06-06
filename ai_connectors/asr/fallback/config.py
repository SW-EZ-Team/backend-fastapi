"""폴백 ASR 설정값 — 기본 tier 순서와 품질 임계값.

모든 값은 환경변수로 override 가능하다.
이 파일은 os 만 import 한다 (순환 import 금지).
"""
from __future__ import annotations

import os

# 기본 tier 순서 — Gemini(클라우드 1순위) → Qwen3 ASR Modal(배포 폴백).
# MLX 로컬 ASR 은 프로덕션 전환으로 제거됐다.
DEFAULT_TIER_MODELS: tuple[str, ...] = (
    "gemini-asr",
    "qwen3-asr-modal",
)


def resolve_tier_models() -> tuple[str, ...]:
    """ASR_FALLBACK_TIERS 환경변수를 파싱해 tier 순서를 결정한다.

    미설정 시 DEFAULT_TIER_MODELS 를 그대로 반환한다.
    형식: "gemini-asr,qwen3-asr-modal"
    """
    raw = os.getenv("ASR_FALLBACK_TIERS", "").strip()
    if not raw:
        return DEFAULT_TIER_MODELS
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts if parts else DEFAULT_TIER_MODELS


def min_chars_per_sec() -> float:
    """한국어 전사 최소 글자/초 임계값 (env: ASR_FALLBACK_MIN_CHARS_PER_SEC)."""
    raw = os.getenv("ASR_FALLBACK_MIN_CHARS_PER_SEC", "").strip()
    try:
        return float(raw) if raw else 1.5
    except ValueError:
        return 1.5


def max_repeat_ngram() -> int:
    """할루시네이션 판정 n-gram 반복 최대 횟수 (env: ASR_FALLBACK_MAX_REPEAT_NGRAM)."""
    raw = os.getenv("ASR_FALLBACK_MAX_REPEAT_NGRAM", "").strip()
    try:
        return int(raw) if raw else 3
    except ValueError:
        return 3


def quality_pass_threshold() -> float:
    """품질 통과 최소 점수 임계값 (env: ASR_FALLBACK_QUALITY_PASS).

    aggregate_quality 점수가 이 값 이상이면 해당 tier 결과를 최종 채택한다.
    """
    raw = os.getenv("ASR_FALLBACK_QUALITY_PASS", "").strip()
    try:
        return float(raw) if raw else 0.6
    except ValueError:
        return 0.6
