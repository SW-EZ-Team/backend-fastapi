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

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tutors", tags=["tutor-preview"])


class PreviewTutorRequest(BaseModel):
    """Spring PreviewTutorRequest 와 동일한 바디.

    슬라이더는 0~100 정수(미설정 허용=None), 토글은 불리언, sampleQuestion 은 필수다.
    """

    toneSlider: int | None = Field(default=None, ge=0, le=100)
    speedSlider: int | None = Field(default=None, ge=0, le=100)
    depthSlider: int | None = Field(default=None, ge=0, le=100)
    questionStyleSlider: int | None = Field(default=None, ge=0, le=100)
    useEmoji: bool | None = None
    useFormalSpeech: bool | None = None
    sampleQuestion: str = Field(min_length=1)


class PreviewTutorResponse(BaseModel):
    """Spring PreviewTutorResponse 와 동일한 응답 — previewText + settingTags."""

    previewText: str
    settingTags: list[str]


@router.post("/{tutorId}/preview", response_model=PreviewTutorResponse)
async def preview_tutor(
    req: PreviewTutorRequest,
    tutorId: str = Path(min_length=1),
) -> PreviewTutorResponse:
    """튜터 설정으로 미리보기 멘트를 동기 생성해 PreviewTutorResponse 로 반환한다.

    생성 실패는 500으로 변환한다 — Spring 은 비2xx/빈 본문을 TUT_004 로 처리한다.
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

    return PreviewTutorResponse(previewText=preview_text, settingTags=setting_tags)
