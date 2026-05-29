"""TTS 생성 파라미터 프로필 유틸.

한 번의 요청에서 기본 프로필과 보수적 재시도 프로필을 분리해
생성 실패나 드리프트를 같은 인터페이스로 다루기 위해 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GenerationProfile:
    """한 번의 TTS 생성 시도에 쓰는 샘플링 파라미터 묶음."""

    temperature: float
    top_k: int
    top_p: float
    repetition_penalty: float


def build_retry_profiles(primary: GenerationProfile) -> list[GenerationProfile]:
    """기본값 뒤에 보수적 재시도 프로필을 붙여 반환한다."""
    fallback = GenerationProfile(
        temperature=min(primary.temperature, 0.6),
        top_k=min(primary.top_k, 20),
        top_p=min(primary.top_p, 0.9),
        repetition_penalty=max(primary.repetition_penalty, 1.15),
    )
    strict_fallback = GenerationProfile(
        temperature=min(primary.temperature, 0.45),
        top_k=min(primary.top_k, 10),
        top_p=min(primary.top_p, 0.85),
        repetition_penalty=max(primary.repetition_penalty, 1.25),
    )
    profiles = [primary, fallback, strict_fallback]
    deduped: list[GenerationProfile] = []
    for profile in profiles:
        if profile not in deduped:
            deduped.append(profile)
    return deduped
