"""TTS V2 음성 프로필 CRUD 라우터.

사용자가 자신의 음성을 등록·조회·삭제할 수 있는 엔드포인트를 제공한다.
DB 연결은 공유 asyncpg 풀(common.db)을 사용하며, 풀 미초기화 시 503 에러를 반환한다.
"""
from __future__ import annotations

import base64
import uuid

from fastapi import APIRouter, HTTPException, Query

from common.db import get_connection
from app.modules.TTS_V2.schemas.voice_profile import (
    CreateVoiceProfileRequest,
    DeleteVoiceProfileResponse,
    VoiceProfileListResponse,
    VoiceProfileSummary,
)
from app.modules.TTS_V2.services.voice_profile_db import (
    create_voice_profile,
    delete_voice_profile,
    get_voice_profile,
    list_user_voice_profiles,
)
from app.modules.TTS_V2.services.voice_profile_storage import (
    delete_audio,
    save_audio,
)

router = APIRouter(tags=["TTS V2 Voice Profiles"])


@router.post("", summary="사용자 음성 프로필 등록")
async def create_voice_profile_endpoint(
    body: CreateVoiceProfileRequest,
) -> VoiceProfileSummary:
    """base64 오디오를 디코딩해 정규화 저장하고, DB에 프로필 메타데이터를 삽입한다."""
    # base64 디코딩 — 실패 시 400 반환
    try:
        audio_bytes = base64.b64decode(body.ref_audio_base64, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"ref_audio_base64 디코딩 실패: {exc}"
        ) from exc
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="빈 오디오 데이터입니다.")

    # 임시 ID로 파일을 먼저 저장해 경로를 확보한다
    temp_id = f"vpf_{uuid.uuid4().hex}"
    ref_audio_url, sample_rate, duration_sec = await save_audio(
        body.user_id, temp_id, audio_bytes
    )
    # DB에 프로필을 삽입한다 — 파일 저장 경로를 ref_audio_url로 사용
    async with get_connection() as db:
        profile_id = await create_voice_profile(
            conn=db,
            user_id=body.user_id,
            name=body.name,
            ref_audio_url=ref_audio_url,
            ref_text=body.ref_text,
            language=body.language,
            sample_rate=sample_rate,
            duration_sec=duration_sec,
            profile_id=temp_id,
        )

    return VoiceProfileSummary(
        profile_id=profile_id,
        name=body.name,
        language=body.language,
        sample_rate=sample_rate,
        duration_sec=duration_sec,
        source="user",
    )


@router.get("", summary="사용자 음성 프로필 목록 조회")
async def list_voice_profiles_endpoint(
    user_id: str = Query(..., min_length=1, max_length=50),
) -> VoiceProfileListResponse:
    """user_id로 사용자의 모든 음성 프로필을 최신순으로 반환한다."""
    async with get_connection() as db:
        records = await list_user_voice_profiles(db, user_id)

    summaries = [
        VoiceProfileSummary(
            profile_id=r.id,
            name=r.name,
            language=r.language,
            sample_rate=r.sample_rate,
            duration_sec=r.duration_sec,
            source="user",
        )
        for r in records
    ]
    return VoiceProfileListResponse(profiles=summaries)


@router.get("/{profile_id}", summary="음성 프로필 단건 조회")
async def get_voice_profile_endpoint(profile_id: str) -> VoiceProfileSummary:
    """profile_id로 단건 조회한다. 없으면 404를 반환한다."""
    async with get_connection() as db:
        record = await get_voice_profile(db, profile_id)

    if record is None:
        raise HTTPException(status_code=404, detail=f"프로필을 찾을 수 없음: {profile_id}")

    return VoiceProfileSummary(
        profile_id=record.id,
        name=record.name,
        language=record.language,
        sample_rate=record.sample_rate,
        duration_sec=record.duration_sec,
        source="user",
    )


@router.delete("/{profile_id}", summary="음성 프로필 삭제")
async def delete_voice_profile_endpoint(
    profile_id: str,
    user_id: str = Query(..., min_length=1, max_length=50),
) -> DeleteVoiceProfileResponse:
    """본인 소유 프로필을 DB + 파일 시스템에서 모두 삭제한다."""
    async with get_connection() as db:
        # 파일 경로를 미리 확보한다 (DB 삭제 후에는 조회 불가)
        record = await get_voice_profile(db, profile_id)
        if record is None or record.user_id != user_id:
            raise HTTPException(
                status_code=404,
                detail=f"프로필을 찾을 수 없거나 삭제 권한이 없음: {profile_id}",
            )
        deleted = await delete_voice_profile(db, profile_id, user_id)

    # DB 삭제 성공 시 로컬 파일도 삭제한다
    if deleted and record is not None:
        delete_audio(record.ref_audio_url)

    return DeleteVoiceProfileResponse(deleted=deleted, profile_id=profile_id)
