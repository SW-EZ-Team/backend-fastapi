"""TTS V2 async 레퍼런스 resolve 헬퍼.

vpf_ prefix 사용자 프로필의 DB 조회가 필요한 async 경로를 분리한다.
sync 헬퍼는 helpers.py 에, 상태 변환·QC 집계는 helpers.py 에 유지한다.
"""
from __future__ import annotations

import os

import asyncpg
from fastapi import HTTPException

from app.modules.TTS_V2.app.routers.helpers import load_profile_ref, resolve_ref
from app.modules.TTS_V2.voice_profiles import is_user_profile


async def load_user_profile_ref(profile_id: str) -> tuple[bytes, str, str]:
    """DB 에 저장된 사용자 음성 프로필의 레퍼런스를 로드한다.

    DB 연결 실패·프로필 없음은 HTTPException 으로 변환해 반환한다.
    """
    from app.modules.TTS_V2.services.voice_profile_db import get_voice_profile
    from app.modules.TTS_V2.services.voice_profile_storage import load_audio

    dsn = os.getenv("DATABASE_URL")
    if dsn is None:
        raise HTTPException(status_code=503, detail="DB 연결을 사용할 수 없습니다.")
    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncpg.connect(dsn)
        record = await get_voice_profile(conn, profile_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB 조회 실패: {exc}") from exc
    finally:
        if conn is not None:
            await conn.close()
    if record is None:
        raise HTTPException(status_code=404, detail=f"사용자 음성 프로필 없음: {profile_id}")
    audio_bytes = load_audio(record.ref_audio_url)
    return audio_bytes, record.ref_text, profile_id


async def resolve_ref_async(
    ref_audio_base64: str | None,
    ref_text: str | None,
    voice_profile_id: str | None = None,
) -> tuple[bytes, str, str]:
    """요청의 레퍼런스 오디오·대본을 결정한다 (async 버전).

    직접 업로드가 있으면 그대로 사용한다.
    vpf_ prefix 프로필은 DB 에서 조회하고, 나머지는 고정 튜터 프로필을 사용한다.
    """
    # 직접 base64 업로드가 있으면 sync resolve_ref 위임
    if ref_audio_base64 is not None or ref_text is not None:
        return resolve_ref(ref_audio_base64, ref_text, voice_profile_id)
    # vpf_ prefix 이면 DB 에서 레퍼런스 조회 — is_user_profile 통과 시 None 아님이 보장된다
    if is_user_profile(voice_profile_id):
        assert voice_profile_id is not None  # is_user_profile 이 None 을 False 로 처리하므로 불변
        return await load_user_profile_ref(voice_profile_id)
    # 기본 고정 튜터 프로필 사용
    return load_profile_ref(voice_profile_id)
