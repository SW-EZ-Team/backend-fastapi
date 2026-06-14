"""튜터 미리보기 API 라우터 — Spring TutorService.previewTutor 가 호출하는 경로.

Spring 발신: POST {fastapi-base}/api/tutors/{tutorId}/preview 로 PreviewTutorRequest 를
JSON 으로 POST하고, RestTemplate 로 **동기 응답** PreviewTutorResponse 를 받는다.
따라서 이 엔드포인트는 백그라운드가 아니라 멘트를 실제 생성해 즉시 본문으로 반환한다.

요청/응답 필드는 Spring DTO(PreviewTutorRequest / PreviewTutorResponse)에 1:1로 맞춘다.
tutorId 는 경로 변수이며 요청 바디에 포함되지 않는다(Spring 도 path 로만 전달).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.app.tutor_preview_generate import generate_tutor_preview
from app.modules.ChapterStudio_V1.pipeline.tts_routing import TutorVoiceProfile
from app.modules.ChapterStudio_V1.pipeline.voice_audio import synthesize_voice_audio

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tutors", tags=["tutor-preview"])


class PreviewTutorRequest(BaseModel):
    """Spring PreviewTutorFastApiRequest 와 동일한 바디.

    슬라이더는 0~100 정수(미설정 허용=None), 토글은 불리언, sampleQuestion 은 필수다.
    voiceSampleUrl 은 Spring 이 서버 보관값에서 채워 보내는 선택 필드다 — 있으면
    보이스클론(qwen3-tts-modal) 경로, 없으면 기본 TTS(gemini-tts) 경로로 합성한다.
    """

    toneSlider: int | None = Field(default=None, ge=0, le=100)
    speedSlider: int | None = Field(default=None, ge=0, le=100)
    depthSlider: int | None = Field(default=None, ge=0, le=100)
    questionStyleSlider: int | None = Field(default=None, ge=0, le=100)
    useEmoji: bool | None = None
    useFormalSpeech: bool | None = None
    sampleQuestion: str = Field(min_length=1)
    voiceSampleUrl: str | None = None


class PreviewTutorResponse(BaseModel):
    """Spring PreviewTutorResponse 와 동일한 응답 — previewText + settingTags + audioUrl.

    audioUrl 은 TTS 합성 성공 시 브라우저가 재생 가능한 오디오 URL, 실패 시 None 이다.
    음성 합성 실패가 텍스트 미리보기까지 막지 않도록 best-effort 로 처리한다.
    """

    previewText: str
    settingTags: list[str]
    audioUrl: str | None = None


async def _synthesize_preview_audio(
    tutor_id: str,
    preview_text: str,
    voice_sample_url: str | None,
    use_formal_speech: bool | None,
) -> str | None:
    """미리보기 멘트를 TTS 로 합성해 오디오 URL 을 반환한다. 실패 시 None (best-effort).

    레슨 파이프라인과 동일한 라우팅을 재사용한다 — 프리셋/커스텀 샘플은 qwen3-tts-modal,
    그 외(및 합성 실패 폴백)는 gemini-tts. 저장은 ObjectStorage_V1(S3/MinIO) 경유.
    """
    profile = TutorVoiceProfile(
        tutor_id=tutor_id,
        is_default_tutor=False,
        voice_sample_url=(voice_sample_url or "").strip(),
        use_formal_speech=True if use_formal_speech is None else bool(use_formal_speech),
        tutor_tagline="",
    )
    try:
        records = await synthesize_voice_audio(
            [{"slide_idx": 0, "script_text": preview_text}],
            tutor_profile=profile,
        )
        audio_url = records[0].get("audio_url") if records else None
        if isinstance(audio_url, str) and audio_url:
            return audio_url
        _LOG.warning("[tutor_preview] TTS 결과에 audio_url 이 없음 — tutorId=%s", tutor_id)
    except Exception as exc:  # noqa: BLE001 — 음성은 부가 기능이라 모든 실패를 삼키고 텍스트만 반환한다
        _LOG.warning("[tutor_preview] 미리보기 TTS 합성 실패 — tutorId=%s, error=%s", tutor_id, exc)
    return None


@router.post("/{tutorId}/preview", response_model=PreviewTutorResponse)
async def preview_tutor(
    req: PreviewTutorRequest,
    tutorId: str = Path(min_length=1),
) -> PreviewTutorResponse:
    """튜터 설정으로 미리보기 멘트를 동기 생성해 PreviewTutorResponse 로 반환한다.

    텍스트 생성 후 같은 멘트를 TTS 로 합성해 audioUrl 을 채운다(실패 시 None).
    텍스트 생성 실패는 500으로 변환한다 — Spring 은 비2xx/빈 본문을 TUT_004 로 처리한다.
    """
    _LOG.debug("[tutor_preview] 미리보기 요청 — tutorId=%s", tutorId)
    try:
        preview_text, setting_tags = await generate_tutor_preview(
            sample_question=req.sampleQuestion,
            tone_slider=req.toneSlider,
            speed_slider=req.speedSlider,
            depth_slider=req.depthSlider,
            question_style_slider=req.questionStyleSlider,
            use_emoji=req.useEmoji,
            use_formal_speech=req.useFormalSpeech,
        )
    except (ConnectorError, ValueError) as exc:
        # 커넥터 정규화 예외(인증/한도/타임아웃 등)와 빈 출력(ValueError)을 5xx로 표면화한다.
        # Spring 은 비2xx/빈 본문을 TUT_004 로 처리하므로 에러를 삼키지 않고 그대로 올린다.
        _LOG.error("[tutor_preview] 미리보기 생성 실패 — tutorId=%s, error=%s", tutorId, exc)
        raise HTTPException(status_code=500, detail="튜터 미리보기 생성에 실패했다.") from exc

    # 음성 합성은 best-effort — 실패해도 텍스트 미리보기는 정상 응답한다.
    audio_url = await _synthesize_preview_audio(
        tutor_id=tutorId,
        preview_text=preview_text,
        voice_sample_url=req.voiceSampleUrl,
        use_formal_speech=req.useFormalSpeech,
    )

    return PreviewTutorResponse(
        previewText=preview_text, settingTags=setting_tags, audioUrl=audio_url
    )
