"""오케스트레이터가 각 AI 모듈을 호출하는 어댑터."""
from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder

from .schemas import AgentJobRequest


async def dispatch_agent_job(request: AgentJobRequest) -> dict[str, Any] | list[Any]:
    """module/action 조합을 실제 라이브러리 진입점 호출로 변환한다."""
    if request.module == "chapter_studio_v1":
        return await _dispatch_chapter_studio(request.action, request.payload)
    if request.module == "tts_v2":
        return await _dispatch_tts(request.action, request.payload)
    if request.module == "exam_forge_v1":
        return await _dispatch_exam_forge(request.action, request.payload)
    if request.module == "ocr_v1":
        return await _dispatch_ocr(request.action, request.payload)
    if request.module == "chat_v1":
        return await _dispatch_chat(request.action, request.payload)
    raise ValueError(f"지원하지 않는 모듈입니다: {request.module}")


async def _dispatch_chapter_studio(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """ChapterStudio 작업을 호출한다."""
    if action != "curriculum_preview":
        raise ValueError("chapter_studio_v1 action은 curriculum_preview만 우선 지원합니다.")
    from app.modules.ChapterStudio_V1.app.curriculum_preview import build_curriculum_preview
    from app.modules.ChapterStudio_V1.app.curriculum_preview_types import CurriculumPreviewRequest

    request_payload = {**payload, "engine": "codex_cli"}
    result = await build_curriculum_preview(CurriculumPreviewRequest.model_validate(request_payload))
    return jsonable_encoder(result)


async def _dispatch_tts(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """TTS_V2 작업을 호출한다."""
    if action != "synthesize":
        raise ValueError("tts_v2 action은 synthesize만 지원합니다.")
    from app.modules.TTS_V2 import synthesize_audiobook
    from app.modules.TTS_V2.schemas.request import TTSV2TextRequest

    body = TTSV2TextRequest.model_validate(payload)
    result = await synthesize_audiobook(
        text=body.text,
        ref_audio_base64=body.ref_audio_base64,
        ref_text=body.ref_text,
        language=body.language,
        speed=body.speed,
        voice_profile_id=body.voice_profile_id,
    )
    return jsonable_encoder(result)


async def _dispatch_exam_forge(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """ExamForge_V1 작업을 호출한다."""
    if action != "generate":
        raise ValueError("exam_forge_v1 action은 generate만 지원합니다.")
    from app.modules.ExamForge_V1 import ExamForgeRequest, generate_exam_forge

    result = await generate_exam_forge(ExamForgeRequest.model_validate(payload))
    return jsonable_encoder(result)


async def _dispatch_ocr(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """OCR_v1 검색 작업을 호출한다."""
    if action != "search":
        raise ValueError("ocr_v1 ingest는 multipart /api/ocr/v1/ingest를 사용하고, job action은 search만 지원합니다.")
    from app.modules.OCR_v1 import OCRv1Pipeline
    from app.modules.OCR_v1.schemas.request import OCRv1SearchRequest

    body = OCRv1SearchRequest.model_validate(payload)
    hits = await OCRv1Pipeline().search(body.query, body.collection_name, body.top_k)
    return {"query": body.query, "hits": jsonable_encoder(hits), "total_found": len(hits)}


async def _dispatch_chat(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Chat_V1 학습 챗봇 작업을 호출한다.

    action "ask"   → 텍스트 채팅 (Claude Sonnet)
    action "voice" → 음성 채팅 (Gemini Flash Live)
    """
    if action == "ask":
        from app.modules.Chat_V1 import ChatRequest, answer_question
        result = await answer_question(ChatRequest.model_validate(payload))
        return jsonable_encoder(result)

    if action == "voice":
        from app.modules.Chat_V1.app.schemas import VoiceChatRequest
        from app.modules.Chat_V1.app.voice_service import answer_voice_question
        result = await answer_voice_question(VoiceChatRequest.model_validate(payload))
        return jsonable_encoder(result)

    raise ValueError("chat_v1 action은 ask 또는 voice만 지원합니다.")
