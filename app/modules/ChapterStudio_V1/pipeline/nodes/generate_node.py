from __future__ import annotations

from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector
from app.modules.ChapterStudio_V1.ai_connectors.registry import get_text_connector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.common.config import lesson_self_repair_enabled
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.backfill import backfill_missing
from app.modules.ChapterStudio_V1.pipeline.payload import (
    GeneratedLessonPayload,
    finalize_payload,
    parse_payload,
    parse_payload_lenient,
)
from app.modules.ChapterStudio_V1.pipeline.parallel_generate import generate_lesson_parallel
from app.modules.ChapterStudio_V1.pipeline.prompt import build_generation_request
from app.modules.ChapterStudio_V1.pipeline.quality import check_payload
from app.modules.ChapterStudio_V1.pipeline.repair import repair_payload
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState

# 컴포넌트 병렬 생성 경로가 출력으로 기록하는 합성 모델명(실제 모델은 커넥터 name).
_PARALLEL_MODEL_TAG = "_parallel"


async def generate_lesson_node(state: ChapterStudioState) -> ChapterStudioState:
    """활성 텍스트 커넥터로 강의 JSON을 생성·검증·보강해 중간 버킷에 담는다.

    모델 인지 분기: connector.supports("batch")가 True면(=Qwen Modal) 강의 산출물을
    컴포넌트별로 병렬 생성한다. False면(=codex/claude) 기존 단일콜 경로를 그대로 쓴다
    (codex/claude 동작·비용 불변). 다운스트림 records(slides/quiz_set/voice_scripts 등)는
    다음 단계인 content_verify 노드가 단 한 번 emit한다(state의 add reducer 중복 방지).
    """
    connector = get_text_connector()
    slide_count = _state_int(state, "slide_count")
    if connector.supports("batch"):
        payload = await generate_lesson_parallel(connector, state, slide_count)
        payload = await _self_repair(connector, payload, slide_count)
        return {"lesson_payload": payload.model_dump(), "generation_model": f"{connector.name}{_PARALLEL_MODEL_TAG}"}
    return await _generate_single_call(connector, state, slide_count)


async def _generate_single_call(
    connector: AIConnector, state: ChapterStudioState, slide_count: int
) -> ChapterStudioState:
    """단일 거대 콜 경로(codex/claude 등 batch 미지원 모델용, 기존 동작 보존)."""
    request = build_generation_request(state)
    response = await connector.generate(request)
    payload = await _parse_robust(connector, request, response.text, slide_count)
    payload = await _self_repair(connector, payload, slide_count)
    return {"lesson_payload": payload.model_dump(), "generation_model": response.model}


async def _parse_robust(
    connector: AIConnector, request: ChapterAIRequest, text: str, slide_count: int
) -> GeneratedLessonPayload:
    """엄격 파싱(codex 빠른 경로) → 실패 시 관대 파싱+보충(Qwen 견고 경로)."""
    try:
        return parse_payload(text, slide_count)
    except ConversionError:
        return await _parse_with_backfill(connector, request, text, slide_count)


async def _parse_with_backfill(
    connector: AIConnector, request: ChapterAIRequest, text: str, slide_count: int
) -> GeneratedLessonPayload:
    """관대 파싱 → 부족 배열 보충 → 최종 엄격 검증. 끝까지 실패하면 강화 지시로 1회 재호출."""
    try:
        lenient = parse_payload_lenient(text)
        filled = await backfill_missing(connector, lenient, slide_count)
        return finalize_payload(filled, slide_count)
    except ConversionError:
        retry = request.model_copy(update={"user": f"{request.user}\n{_RETRY_HINT}", "temperature": 0.2})
        retry_response = await connector.generate(retry)
        lenient = parse_payload_lenient(retry_response.text)
        filled = await backfill_missing(connector, lenient, slide_count)
        return finalize_payload(filled, slide_count)


async def _self_repair(
    connector: AIConnector, payload: GeneratedLessonPayload, slide_count: int
) -> GeneratedLessonPayload:
    """self-check로 미달 항목을 찾아 1회 targeted-repair로 보강한다(graceful)."""
    if not lesson_self_repair_enabled():
        return payload
    report = check_payload(payload)
    return await repair_payload(connector, payload, report, slide_count)


_RETRY_HINT = (
    "직전 응답이 JSON 검증에 실패했다. 이번에는 설명·사고과정 없이 유효한 단일 JSON 객체만 "
    "출력하고, slides·quizzes·voice_scripts 개수와 slide_idx 계약을 정확히 지킨다."
)


def _state_int(state: ChapterStudioState, key: str) -> int:
    value = state.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} 정수가 필요하다.")
    return value


__all__ = ["generate_lesson_node"]
