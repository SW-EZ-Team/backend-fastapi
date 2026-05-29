"""TTS V2 — API 라우터.

텍스트 직접 입력(/api/tts-v2)과 파일 업로드(/api/tts-v2/file) 두 엔드포인트를 제공한다.
상태 구성·변환·QC 집계 헬퍼는 helpers.py 로 분리해 200줄 제한을 준수한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, UploadFile

from app.modules.TTS_V2.pipeline.config import TTS_V2_MAX_RETRIES, TTS_V2_QC_ENGINE
from app.modules.TTS_V2.pipeline.graph import get_compiled_graph
from app.modules.TTS_V2.schemas.request import TTSV2TextRequest
from app.modules.TTS_V2.schemas.response import TTSV2Response
from app.modules.TTS_V2.schemas.state import AudiobookState
from app.modules.TTS_V2.voice_profiles import list_voice_profile_summaries
from app.modules.TTS_V2.app.routers.helpers import (
    build_initial_state,
    state_to_response,
)
from app.modules.TTS_V2.app.routers.helpers_async import resolve_ref_async

router = APIRouter(tags=["TTS V2"])


@router.post("", response_model=TTSV2Response, summary="텍스트 직접 입력 TTS 합성")
async def synthesize_text(body: TTSV2TextRequest) -> TTSV2Response:
    """JSON 바디로 텍스트를 받아 오디오북 파이프라인을 실행한다.

    ref_audio_base64 / ref_text 가 None 이면 기본 고정 튜터 프로필을 사용한다.
    """
    ref_audio_bytes, ref_text, resolved_profile_id = await resolve_ref_async(
        body.ref_audio_base64, body.ref_text, body.voice_profile_id
    )
    initial_state = build_initial_state(
        text=body.text,
        ref_audio_bytes=ref_audio_bytes,
        ref_text=ref_text,
        language=body.language,
        max_retries=TTS_V2_MAX_RETRIES,
        skip_planner=body.skip_planner,
        skip_postfx=body.skip_postfx,
        qc_engine=body.qc_engine,
        voice_profile_id=resolved_profile_id,
        speed=body.speed,
    )
    graph = get_compiled_graph()
    result: AudiobookState = await graph.ainvoke(initial_state)
    return state_to_response(result, body.qc_engine)


@router.post("/file", response_model=TTSV2Response, summary="파일 업로드 TTS 합성")
async def synthesize_file(
    text_file: UploadFile,
    ref_audio: UploadFile | None = None,
    ref_text: str | None = Form(default=None),
    voice_profile_id: str | None = Form(default=None),
    language: str = Form(default="ko"),
    speed: float = Form(default=1.0),
    skip_planner: bool = Form(default=False),
    skip_postfx: bool = Form(default=False),
    qc_engine: str = Form(default=TTS_V2_QC_ENGINE),
) -> TTSV2Response:
    """텍스트 파일(.txt/.md)을 업로드해 오디오북 파이프라인을 실행한다.

    ref_audio 폼 필드가 없으면 기본 고정 튜터 프로필을 레퍼런스로 사용한다.
    """
    raw_text = (await text_file.read()).decode("utf-8")

    if ref_audio is not None:
        ref_audio_bytes: bytes = await ref_audio.read()
        if not ref_audio_bytes:
            raise HTTPException(status_code=400, detail="빈 레퍼런스 음성입니다.")
        if ref_text is None or not ref_text.strip():
            raise HTTPException(
                status_code=400,
                detail="직접 레퍼런스 음성 업로드 시 ref_text 가 필요합니다.",
            )
        ref_text = ref_text.strip()
        resolved_profile_id = "custom"
    else:
        # 레퍼런스 오디오 없으면 프로필 사용 — vpf_ 사용자 프로필도 지원
        ref_audio_bytes, ref_text, resolved_profile_id = await resolve_ref_async(
            None, None, voice_profile_id
        )

    initial_state = build_initial_state(
        text=raw_text,
        ref_audio_bytes=ref_audio_bytes,
        ref_text=ref_text,
        language=language,
        max_retries=TTS_V2_MAX_RETRIES,
        skip_planner=skip_planner,
        skip_postfx=skip_postfx,
        qc_engine=qc_engine,
        voice_profile_id=resolved_profile_id,
        speed=speed,
    )
    graph = get_compiled_graph()
    result: AudiobookState = await graph.ainvoke(initial_state)
    return state_to_response(result, qc_engine)


@router.get("/voices", summary="고정 튜터 음성 프로필 목록")
async def list_voices() -> dict[str, object]:
    """프론트가 선택 가능한 고정 튜터 음성 목록을 조회한다."""
    return {"profiles": list_voice_profile_summaries()}
