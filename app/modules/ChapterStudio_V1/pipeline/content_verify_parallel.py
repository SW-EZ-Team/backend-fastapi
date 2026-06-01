"""병렬 2차 내용 검증 + 병렬 교정 (최대 2라운드).

content_verify.py(직렬 1회)의 병렬·다라운드판이다. 슬라이드·퀴즈·음성 세 그룹을 동시에
검증(asyncio.gather)하고, 이슈가 있는 그룹만 동시에 교정한다. 교정 후 재검증해 잔존 오류가
있으면 최대 CHAPTERSTUDIO_VERIFY_MAX_ROUNDS(기본 2)까지 반복한다(무한루프 방지).

길이 게이트: voice_script가 900자(CHAPTERSTUDIO_VOICE_MIN_CHARS) 미만이면 LLM 판단 없이
len()으로 확장 교정 대상에 강제 포함한다(xgrammar minLength 미강제 실측 갭 대응).

설계 원칙(정직하게):
    - 검증/교정은 품질 향상 장치다. 실패하면 원본을 유지(graceful), 예외로 죽지 않는다.
    - return_exceptions로 그룹별 예외를 받아 한 그룹 실패가 전체로 번지지 않게 한다.
    - 교정 병합이 slide_idx 계약을 깨면 원본으로 되돌린다(다운스트림 계약 불변).
    - codex 경로(길이 충족 시)는 게이트 통과 → no-op.

공개 API:
    - verify_and_correct_parallel(connector, payload, slide_count) -> GeneratedLessonPayload
"""
from __future__ import annotations

import asyncio
import json

from pydantic import ValidationError

from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.common.config import (
    verify_max_rounds,
    voice_length_gate_enabled,
    voice_min_chars,
)
from app.modules.ChapterStudio_V1.common.logging import logger
from app.modules.ChapterStudio_V1.pipeline.content_verify_merge import (
    apply_corrections,
    combine_corrections,
    indices_intact,
    parse_correction,
    parse_errors,
)
from app.modules.ChapterStudio_V1.pipeline.content_verify_prompts import (
    correct_system,
    correct_user_group,
    verify_system,
    verify_user_group,
)
from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload
from app.modules.ChapterStudio_V1.pipeline.voice_length_gate import length_gate_errors

# 검증/교정 토큰 상한 — content_verify.py와 동일 기준.
_VERIFY_MAX_TOKENS = 8000
_CORRECT_MAX_TOKENS = 16000
# 동시에 검증·교정하는 컴포넌트 그룹.
_GROUPS = ("slides", "quizzes", "voice")


async def verify_and_correct_parallel(
    connector: AIConnector,
    payload: GeneratedLessonPayload,
    slide_count: int,
) -> GeneratedLessonPayload:
    """그룹별 병렬 검증→병렬 교정을 최대 max_rounds 반복해 교정된 payload를 반환한다.

    각 라운드: ① LLM 병렬 검증(3그룹 동시) ② 결정적 voice 길이 게이트 오류 추가
    ③ 오류 있는 그룹만 병렬 교정 ④ 재검증(다음 라운드 입력). max_rounds 후 잔존 시 경고만.
    """
    max_r = verify_max_rounds()
    current = payload
    for round_num in range(1, max_r + 1):
        errors = await _collect_errors(connector, current)
        if not errors:
            return current
        logger.warning(
            "parallel_verify: 라운드 {}/{} 오류 {}건 검출 → 병렬 교정",
            round_num, max_r, len(errors),
        )
        corrected = await _correct_all_groups(connector, current, errors, slide_count)
        if corrected is current:
            # 교정 자체가 실패했으면 더 반복해도 의미 없다 — 현재 상태 유지.
            return current
        current = corrected
    # max_rounds 완료 후 잔존 확인(경고만, 교정은 하지 않는다).
    remaining = await _collect_errors(connector, current)
    if remaining:
        logger.warning("parallel_verify: {}라운드 후에도 오류 {}건 잔존(추가 교정은 하지 않는다)", max_r, len(remaining))
    return current


async def _collect_errors(
    connector: AIConnector, payload: GeneratedLessonPayload
) -> list[dict[str, object]]:
    """LLM 병렬 검증 오류 + 결정적 voice 길이 게이트 오류를 합산한다."""
    llm_errors = await _verify_all_groups(connector, payload)
    if not voice_length_gate_enabled():
        return llm_errors
    gate_errors = length_gate_errors(payload, voice_min_chars())
    if gate_errors:
        existing_voice_idx = {
            err.get("slide_idx")
            for err in llm_errors
            if str(err.get("field", "")) == "voice"
        }
        # 이미 LLM이 오류로 잡은 인덱스는 중복 추가하지 않는다(교정 지시 충돌 방지).
        new_gate = [e for e in gate_errors if e.get("slide_idx") not in existing_voice_idx]
        if new_gate:
            logger.warning("parallel_verify: voice 길이 게이트 {}건 추가(LLM 미검출 미달 항목)", len(new_gate))
        return llm_errors + new_gate
    return llm_errors


async def _verify_all_groups(
    connector: AIConnector, payload: GeneratedLessonPayload
) -> list[dict[str, object]]:
    """슬라이드·퀴즈·음성을 동시에 검증하고 오류를 모은다(그룹 실패는 graceful)."""
    results = await asyncio.gather(
        *[_verify_group(connector, payload, group) for group in _GROUPS],
        return_exceptions=True,
    )
    errors: list[dict[str, object]] = []
    for group, result in zip(_GROUPS, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("parallel_verify: 그룹({}) 검증 실패 → 무시(graceful): {}", group, result)
            continue
        errors.extend(result)
    return errors


async def _verify_group(
    connector: AIConnector, payload: GeneratedLessonPayload, group: str
) -> list[dict[str, object]]:
    """한 그룹 검증 1회. 응답이 깨지면 빈 목록(graceful)."""
    request = ChapterAIRequest(
        system=verify_system(),
        user=verify_user_group(payload, group),
        max_tokens=_VERIFY_MAX_TOKENS,
        temperature=0.0,
        extra={"schema": "content_verify", "content_verify": True},
    )
    try:
        response = await connector.generate(request)
        return parse_errors(response.text)
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        logger.warning("parallel_verify: 그룹({}) 응답 파싱 실패 → 빈 목록({})", group, exc)
        return []


async def _correct_all_groups(
    connector: AIConnector,
    payload: GeneratedLessonPayload,
    errors: list[dict[str, object]],
    slide_count: int,
) -> GeneratedLessonPayload:
    """이슈가 있는 그룹만 동시에 교정해 병합한다(인덱스 깨지면 원본 유지)."""
    affected = _affected_groups(errors)
    if not affected:
        return payload
    results = await asyncio.gather(
        *[_correct_group(connector, payload, errors, group) for group in affected],
        return_exceptions=True,
    )
    partials = []
    for group, result in zip(affected, results, strict=True):
        if isinstance(result, BaseException) or result is None:
            logger.warning("parallel_verify: 그룹({}) 교정 실패 → 해당 그룹은 원본 유지", group)
            continue
        partials.append(result)
    if not partials:
        return payload
    merged = apply_corrections(payload, combine_corrections(partials))
    if not indices_intact(merged, slide_count):
        logger.warning("parallel_verify: 교정 병합이 인덱스 계약을 깨뜨려 원본으로 되돌린다")
        return payload
    return merged


async def _correct_group(
    connector: AIConnector,
    payload: GeneratedLessonPayload,
    errors: list[dict[str, object]],
    group: str,
):
    """한 그룹 교정 1회. 응답이 깨지면 None(graceful)."""
    request = ChapterAIRequest(
        system=correct_system(),
        user=correct_user_group(payload, errors, group),
        max_tokens=_CORRECT_MAX_TOKENS,
        temperature=0.1,
        extra={"schema": "content_correct", "content_correct": True},
    )
    try:
        response = await connector.generate(request)
        return parse_correction(response.text)
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        logger.warning("parallel_verify: 그룹({}) 교정 응답 파싱 실패({})", group, exc)
        return None


def _affected_groups(errors: list[dict[str, object]]) -> list[str]:
    """오류가 보고된 그룹만 골라낸다(field=slide/quiz/voice → 그룹명)."""
    fields = {str(err.get("field", "")) for err in errors}
    mapping = {"slide": "slides", "quiz": "quizzes", "voice": "voice"}
    return [group for field, group in mapping.items() if field in fields]


__all__ = ["verify_and_correct_parallel"]
