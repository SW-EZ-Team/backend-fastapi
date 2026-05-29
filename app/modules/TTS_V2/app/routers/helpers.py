"""TTS V2 라우터 헬퍼 — 상태 구성·변환·QC 집계 원자 함수 모음.

라우터 파일의 200줄 제한 준수를 위해 파이프라인 외 모든 헬퍼를 이 파일로 분리한다.
async DB 조회 헬퍼는 helpers_async.py 에 별도 분리한다.
"""
from __future__ import annotations

import base64

from fastapi import HTTPException

from app.modules.TTS_V2.schemas.response import TTSV2Response
from app.modules.TTS_V2.schemas.state import AudiobookState
from app.modules.TTS_V2.voice_profiles import resolve_voice_profile


def load_profile_ref(profile_id: str | None = None) -> tuple[bytes, str, str]:
    """고정 튜터 프로필의 레퍼런스 오디오와 대본을 로드한다.

    파일이 존재하지 않으면 RuntimeError 를 발생시켜 서버 설정 오류를 명시한다.
    vpf_ prefix 프로필은 처리하지 않으며, None 이 반환되면 HTTPException 을 발생시킨다.
    """
    try:
        profile = resolve_voice_profile(profile_id)
    except RuntimeError as exc:
        if str(exc).startswith("알 수 없는 음성 프로필"):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise
    if profile is None:
        raise HTTPException(status_code=400, detail=f"튜터 프로필이 아님: {profile_id}")
    audio_bytes, ref_text = profile.read_ref()
    return audio_bytes, ref_text, profile.profile_id


def resolve_ref(
    ref_audio_base64: str | None,
    ref_text: str | None,
    voice_profile_id: str | None = None,
) -> tuple[bytes, str, str]:
    """요청의 레퍼런스 오디오·대본을 결정한다.

    직접 업로드가 완성되어 있으면 업로드 값을 사용하고, 아니면 고정 튜터 프로필을 사용한다.
    base64 디코딩 실패는 400 에러로 클라이언트에 반환한다.
    vpf_ prefix 프로필이나 async 경로가 필요하면 helpers_async.resolve_ref_async 를 사용한다.
    """
    # 직접 레퍼런스가 없으면 고정 튜터 프로필로 대체
    if ref_audio_base64 is None and ref_text is None:
        return load_profile_ref(voice_profile_id)
    # 절반만 제공된 경우 명시적 오류 반환
    if ref_audio_base64 is None or ref_text is None or not ref_text.strip():
        raise HTTPException(
            status_code=400,
            detail="직접 레퍼런스 음성은 ref_audio_base64 와 ref_text 를 함께 제공해야 합니다.",
        )
    try:
        audio_bytes = base64.b64decode(ref_audio_base64, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"ref_audio_base64 디코딩 실패: {exc}",
        ) from exc
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="빈 레퍼런스 음성입니다.")
    return audio_bytes, ref_text.strip(), "custom"


def build_initial_state(
    text: str,
    ref_audio_bytes: bytes,
    ref_text: str,
    language: str,
    max_retries: int,
    skip_planner: bool,
    skip_postfx: bool,
    qc_engine: str,
    voice_profile_id: str,
    speed: float,
) -> AudiobookState:
    """API 요청으로부터 초기 파이프라인 상태를 구성한다.

    merged_audio_bytes·total_duration_sec 등 파이프라인이 채우는 필드는
    빈 값(None / 0.0)으로 초기화한다.
    """
    return AudiobookState(
        input_type="text",
        raw_text=text,
        file_content=None,
        ref_audio_bytes=ref_audio_bytes,
        ref_text=ref_text,
        ref_sample_rate=0,
        language=language,
        sections=[],
        chunks=[],
        current_phase="init",
        max_retries=max_retries,
        failed_chunks=[],
        merged_audio_bytes=None,
        total_duration_sec=0.0,
        pipeline_status="loading",
        error_message=None,
        timings={},
        skip_planner=skip_planner,
        skip_postfx=skip_postfx,
        qc_engine=qc_engine,
        voice_profile_id=voice_profile_id,
        speed=speed,
    )


def avg_metric(chunks: list, key: str) -> float | None:
    """청크 목록에서 특정 QC 지표(cer/wer)의 평균을 계산한다.

    None 이 아닌 값만 포함하며 유효값이 없으면 None 을 반환한다.
    """
    values = [c.get(key, 0.0) for c in chunks if c.get(key) is not None]
    return sum(values) / len(values) if values else None


def qc_reason_counts(chunks: list) -> dict[str, int]:
    """청크별 QC 사유를 집계한다."""
    counts: dict[str, int] = {}
    for chunk in chunks:
        reason = str(chunk.get("qc_reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def chunk_qc_reasons(chunks: list) -> list[dict[str, str]]:
    """프론트가 실패 청크 원인을 표시할 수 있게 최소 필드만 반환한다."""
    return [
        {
            "chunk_id": str(chunk.get("chunk_id", "")),
            "qc_reason": str(chunk.get("qc_reason") or "unknown"),
        }
        for chunk in chunks
    ]


def state_to_response(state: AudiobookState, qc_engine: str) -> TTSV2Response:
    """파이프라인 결과 상태를 API 응답으로 변환한다.

    merged_audio_bytes 가 None 이면 pipeline_status·error_message 를
    포함한 500 에러를 반환한다.
    """
    merged_audio = state.get("merged_audio_bytes")
    # None 과 빈 바이트 모두 파이프라인 실패로 처리한다
    if merged_audio is None or merged_audio == b"":
        err = state.get("error_message") or "파이프라인이 오디오를 생성하지 못했습니다."
        raise HTTPException(status_code=500, detail=err)

    audio_b64 = base64.b64encode(merged_audio).decode("ascii")
    chunks = state.get("chunks", [])
    failed_ids: list[str] = state.get("failed_chunks", [])

    return TTSV2Response(
        audio_base64=audio_b64,
        total_duration_sec=state.get("total_duration_sec", 0.0),
        chunk_count=len(chunks),
        failed_chunk_count=len(failed_ids),
        failed_chunk_ids=failed_ids,
        avg_cer=avg_metric(chunks, "cer"),
        avg_wer=avg_metric(chunks, "wer"),
        qc_reason_counts=qc_reason_counts(chunks),
        chunk_qc_reasons=chunk_qc_reasons(chunks),
        timings=state.get("timings", {}),
        qc_engine_used=qc_engine,
    )
