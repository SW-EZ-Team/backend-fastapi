"""TTS V2 고정 튜터 음성 프로필 로더."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast

_VOICE_SAMPLES_DIR = Path(__file__).resolve().parent / "voice_samples"
_MANIFEST_PATH = _VOICE_SAMPLES_DIR / "tutor_voice_profiles.json"


@dataclass(frozen=True)
class VoiceProfile:
    """하나의 고정 튜터 음성 프로필."""

    profile_id: str
    display_name: str
    tone: str
    ref_audio_path: Path
    ref_text_path: Path
    language: str
    duration_sec: float
    sample_rate: int

    def read_ref(self) -> tuple[bytes, str]:
        """참조 오디오와 참조 대본을 함께 읽는다."""
        if not self.ref_audio_path.exists():
            raise RuntimeError(f"레퍼런스 오디오 파일이 없음: {self.ref_audio_path}")
        if not self.ref_text_path.exists():
            raise RuntimeError(f"레퍼런스 대본 파일이 없음: {self.ref_text_path}")
        return (
            self.ref_audio_path.read_bytes(),
            self.ref_text_path.read_text(encoding="utf-8").strip(),
        )


def _as_str(item: dict[str, object], key: str) -> str:
    """manifest 필수 문자열 필드를 안전하게 꺼낸다."""
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"음성 프로필 manifest 필수 문자열 누락: {key}")
    return value.strip()


def _as_float(item: dict[str, object], key: str) -> float:
    """manifest 숫자 필드를 float 로 정규화한다."""
    value = item.get(key)
    if not isinstance(value, int | float):
        raise RuntimeError(f"음성 프로필 manifest 필수 숫자 누락: {key}")
    return float(value)


def _as_int(item: dict[str, object], key: str) -> int:
    """manifest 숫자 필드를 int 로 정규화한다."""
    value = item.get(key)
    if not isinstance(value, int):
        raise RuntimeError(f"음성 프로필 manifest 필수 정수 누락: {key}")
    return value


def _load_manifest() -> dict[str, object]:
    """음성 프로필 manifest JSON 을 읽는다."""
    if not _MANIFEST_PATH.exists():
        raise RuntimeError(f"음성 프로필 manifest 파일이 없음: {_MANIFEST_PATH}")
    return cast(dict[str, object], json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))


def _build_profile(item: dict[str, object]) -> VoiceProfile:
    """manifest 항목 하나를 VoiceProfile 로 변환한다."""
    return VoiceProfile(
        profile_id=_as_str(item, "profile_id"),
        display_name=_as_str(item, "display_name"),
        tone=_as_str(item, "tone"),
        ref_audio_path=_VOICE_SAMPLES_DIR / _as_str(item, "ref_audio_path"),
        ref_text_path=_VOICE_SAMPLES_DIR / _as_str(item, "ref_text_path"),
        language=_as_str(item, "language"),
        duration_sec=_as_float(item, "duration_sec"),
        sample_rate=_as_int(item, "sample_rate"),
    )


@lru_cache(maxsize=1)
def load_voice_profiles() -> dict[str, VoiceProfile]:
    """등록된 고정 튜터 음성 프로필을 profile_id 기준 dict 로 반환한다."""
    manifest = _load_manifest()
    raw_profiles = manifest.get("profiles")
    if not isinstance(raw_profiles, list):
        raise RuntimeError("음성 프로필 manifest 의 profiles 가 list 가 아님")
    profiles = [_build_profile(cast(dict[str, object], item)) for item in raw_profiles]
    return {profile.profile_id: profile for profile in profiles}


def get_default_voice_profile_id() -> str:
    """환경변수 우선으로 기본 튜터 음성 프로필 ID 를 반환한다."""
    env_profile = os.getenv("TTS_V2_DEFAULT_VOICE_PROFILE", "").strip()
    if env_profile:
        return env_profile
    manifest = _load_manifest()
    default_id = manifest.get("default_profile_id")
    return default_id if isinstance(default_id, str) and default_id else "tutor_1"


def is_user_profile(profile_id: str | None) -> bool:
    """vpf_ prefix 로 시작하는 사용자 업로드 프로필인지 확인한다."""
    return bool(profile_id and profile_id.startswith("vpf_"))


def resolve_voice_profile(profile_id: str | None = None) -> VoiceProfile | None:
    """profile_id 로 고정 튜터 음성 프로필을 찾는다.

    vpf_ prefix 프로필은 DB 조회가 필요하므로 None 을 반환한다 — 호출자가 처리해야 한다.
    """
    # 사용자 업로드 프로필은 DB 조회가 필요하므로 None 반환
    if is_user_profile(profile_id):
        return None
    resolved_id = (profile_id or get_default_voice_profile_id()).strip()
    profiles = load_voice_profiles()
    if resolved_id not in profiles:
        known = ", ".join(sorted(profiles))
        raise RuntimeError(f"알 수 없는 음성 프로필: {resolved_id}. 등록값: {known}")
    return profiles[resolved_id]


def list_voice_profile_summaries() -> list[dict[str, object]]:
    """프론트 설정 패널에서 사용할 공개 프로필 요약을 반환한다."""
    return [
        {
            "profile_id": profile.profile_id,
            "display_name": profile.display_name,
            "tone": profile.tone,
            "language": profile.language,
            "duration_sec": profile.duration_sec,
            "sample_rate": profile.sample_rate,
        }
        for profile in load_voice_profiles().values()
    ]
