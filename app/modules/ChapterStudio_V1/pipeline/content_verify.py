"""강의 산출물 내용 정확성(사실·논리) 검증 + 교정 패스.

형식/분량 self-check(quality.py)+targeted-repair(repair.py) **다음** 단계로, 생성된 강의의
슬라이드 본문·퀴즈 해설·음성대본의 예시·주장에 섞인 사실 오류·논리 모순·틀린 예시·정의
오류를 LLM 검증 패스 1회로 탐지하고, 명백한 오류만 1회 targeted 교정한 뒤 1회까지 재검증한다.

설계 원칙(정직하게):
    - 검증/교정은 품질 향상 장치다. 실패하면 원본을 유지(graceful)하고 절대 예외로 죽지 않는다.
    - 교정은 검증기가 "명백한 오류"라고 지목한 것만 손댄다(오탐 방지). 확신 낮으면 원본 유지.
    - 슬라이드 인덱스·키 계약은 불변. 병합 후 깨지면 원본으로 되돌린다.
    - 무한루프 방지: 교정 후 재검증은 1회까지.

공개 API:
    - verify_and_correct(connector, payload, slide_count) : 교정된 payload(또는 원본)를 반환.
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.common.logging import logger
from app.modules.ChapterStudio_V1.pipeline.content_verify_merge import (
    apply_corrections,
    indices_intact,
    parse_correction,
    parse_errors,
)
from app.modules.ChapterStudio_V1.pipeline.content_verify_prompts import (
    correct_system,
    correct_user,
    verify_system,
    verify_user,
)
from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload

# 검증/교정 호출당 토큰 상한 — 오류 목록 또는 교정 묶음을 한 번에 받을 여유값.
_VERIFY_MAX_TOKENS = 8000
_CORRECT_MAX_TOKENS = 16000


async def verify_and_correct(
    connector: AIConnector,
    payload: GeneratedLessonPayload,
    slide_count: int,
) -> GeneratedLessonPayload:
    """내용 검증→교정→재검증을 1회씩 수행해 교정된 payload(또는 원본)를 반환한다."""
    errors = await _run_verify(connector, payload)
    if not errors:
        return payload
    logger.warning("content_verify: 1차 검증에서 오류 {}건 검출 → 교정 시도", len(errors))
    corrected = await _run_correct(connector, payload, errors, slide_count)
    if corrected is payload:
        # 교정 실패·인덱스 깨짐 → 원본 유지(이미 _run_correct가 경고를 남긴다).
        return payload
    remaining = await _run_verify(connector, corrected)
    if remaining:
        logger.warning("content_verify: 교정 후에도 오류 {}건 잔존(재교정은 하지 않는다)", len(remaining))
    return corrected


async def _run_verify(
    connector: AIConnector, payload: GeneratedLessonPayload
) -> list[dict[str, object]]:
    """검증 패스 1회. 실패하면 빈 목록을 반환(graceful)하고 경고를 남긴다."""
    request = ChapterAIRequest(
        system=verify_system(),
        user=verify_user(payload),
        max_tokens=_VERIFY_MAX_TOKENS,
        temperature=0.0,
        extra={"schema": "content_verify", "content_verify": True},
    )
    try:
        response = await connector.generate(request)
        return parse_errors(response.text)
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        logger.warning("content_verify: 검증 응답 파싱 실패 → 원본 유지({})", exc)
        return []


async def _run_correct(
    connector: AIConnector,
    payload: GeneratedLessonPayload,
    errors: list[dict[str, object]],
    slide_count: int,
) -> GeneratedLessonPayload:
    """교정 패스 1회. 실패·인덱스 깨짐이면 원본을 그대로 반환(graceful)한다."""
    request = ChapterAIRequest(
        system=correct_system(),
        user=correct_user(payload, errors),
        max_tokens=_CORRECT_MAX_TOKENS,
        temperature=0.1,
        extra={"schema": "content_correct", "content_correct": True},
    )
    try:
        response = await connector.generate(request)
        result = parse_correction(response.text)
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        logger.warning("content_verify: 교정 응답 파싱 실패 → 원본 유지({})", exc)
        return payload
    merged = apply_corrections(payload, result)
    if not indices_intact(merged, slide_count):
        logger.warning("content_verify: 교정 병합이 인덱스 계약을 깨뜨려 원본으로 되돌린다")
        return payload
    return merged


__all__ = ["verify_and_correct"]
