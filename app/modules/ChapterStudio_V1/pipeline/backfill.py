"""부족한 배열(quizzes/voice_scripts)을 targeted-repair로 보충한다.

실제 Qwen3.6(Modal) 테스트에서 slide_count=10인데 quizzes를 5개만 생성하는 사례가
관측됐다 — guided_json minItems가 xgrammar에서 배열 길이까지 강제하지 못해 모델이 뒤쪽
배열을 적게 만든다. 이 모듈은 부족분을 hard-fail 대신 추가 LLM 호출로 채워 slide_count
계약(slide_idx 0..n-1 완전집합)을 맞춘다.

보충 경로(Modal guided_json 재사용):
    - 빠진 quiz : schema_kind="supporting_materials"(quizzes+assignment)로 묶어 재요청한다.
    - 빠진 voice: schema_kind="voice_script"로 slide_idx 하나씩 재요청한다.

설계 원칙:
    - codex(gpt-5.5)처럼 10/10/10 정확 출력이면 부족분이 0이라 호출이 전혀 없다(비용·동작 불변).
    - 보충은 배열당 최대 1회(quiz 1묶음 + voice는 빠진 인덱스만)다. 무한루프를 만들지 않는다.
    - slides 부족은 보충 대상이 아니다 — 슬라이드 HTML은 생성 핵심이므로 ConversionError로 드러낸다.
    - 보충 실패는 graceful: 가능한 만큼만 채우고, 최종 계약 강제는 finalize_payload가 맡는다.

공개 API:
    - backfill_missing(connector, lenient, slide_count) : 부족분을 채운 LenientLessonPayload 반환.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError

from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.backfill_prompts import (
    QuizBackfillResult,
    VoiceBackfillItem,
    build_quiz_backfill_request,
    build_voice_backfill_request,
    parse_quiz_backfill,
    parse_voice_backfill,
)
from app.modules.ChapterStudio_V1.pipeline.payload import (
    GeneratedQuiz,
    GeneratedVoiceScript,
    LenientLessonPayload,
    SlideIndexed,
)

# _safe_generate 파싱 결과 타입(quiz 묶음 또는 voice 단건).
_Parsed = TypeVar("_Parsed", QuizBackfillResult, VoiceBackfillItem)


async def backfill_missing(
    connector: AIConnector, lenient: LenientLessonPayload, slide_count: int
) -> LenientLessonPayload:
    """quizzes/voice_scripts의 빠진 slide_idx를 보충한 payload를 반환한다(graceful)."""
    _require_slides_complete(lenient, slide_count)
    quizzes = await _backfill_quizzes(connector, lenient, slide_count)
    voices = await _backfill_voices(connector, lenient, slide_count)
    return lenient.model_copy(update={"quizzes": quizzes, "voice_scripts": voices})


def _require_slides_complete(lenient: LenientLessonPayload, slide_count: int) -> None:
    """슬라이드 본문이 부족하면 보충 불가이므로 명확한 에러로 드러낸다(삼키지 않음)."""
    indices = {slide.slide_idx for slide in lenient.slides}
    if indices != set(range(slide_count)):
        raise ConversionError(
            f"slides slide_idx가 불완전하다(보충 불가): 기대 0..{slide_count - 1}, 실제 {sorted(indices)}."
        )


async def _backfill_quizzes(
    connector: AIConnector, lenient: LenientLessonPayload, slide_count: int
) -> list[GeneratedQuiz]:
    """빠진 quiz slide_idx를 supporting_materials 스키마로 한 묶음 재요청해 채운다."""
    missing = _missing_indices(lenient.quizzes, slide_count)
    if not missing:
        return list(lenient.quizzes)
    result = await _request_quizzes(connector, lenient, missing, slide_count)
    if result is None:
        return list(lenient.quizzes)
    return _merge_quizzes(lenient.quizzes, result, missing)


async def _backfill_voices(
    connector: AIConnector, lenient: LenientLessonPayload, slide_count: int
) -> list[GeneratedVoiceScript]:
    """빠진 voice slide_idx를 voice_script 스키마로 인덱스별 재요청해 채운다."""
    missing = _missing_indices(lenient.voice_scripts, slide_count)
    if not missing:
        return list(lenient.voice_scripts)
    filled = list(lenient.voice_scripts)
    for idx in missing:
        script = await _request_voice(connector, lenient, idx, slide_count)
        if script is not None:
            filled.append(script)
    return filled


async def _request_quizzes(
    connector: AIConnector,
    lenient: LenientLessonPayload,
    missing: list[int],
    slide_count: int,
) -> QuizBackfillResult | None:
    """supporting_materials 재요청 1회 — 응답이 깨지면 None(graceful)."""
    request = build_quiz_backfill_request(lenient, missing, slide_count)
    return await _safe_generate(connector, request, parse_quiz_backfill)


async def _request_voice(
    connector: AIConnector,
    lenient: LenientLessonPayload,
    slide_idx: int,
    slide_count: int,
) -> GeneratedVoiceScript | None:
    """voice_script 재요청 1회 — 응답이 깨지면 None(graceful)."""
    request = build_voice_backfill_request(lenient, slide_idx, slide_count)
    parsed = await _safe_generate(connector, request, parse_voice_backfill)
    if parsed is None or parsed.slide_idx != slide_idx:
        # 인덱스가 어긋나면 신뢰할 수 없으므로 채우지 않는다(엉뚱한 슬라이드 오염 방지).
        return None
    return GeneratedVoiceScript(slide_idx=slide_idx, script_text=parsed.script_text)


async def _safe_generate(
    connector: AIConnector,
    request: ChapterAIRequest,
    parse_fn: Callable[[str], _Parsed],
) -> _Parsed | None:
    """generate + 파싱을 graceful하게 감싼다 — 깨진 응답이면 None을 반환한다."""
    try:
        response = await connector.generate(request)
        return parse_fn(response.text)
    except (ValueError, ValidationError, json.JSONDecodeError, ConversionError):
        return None


def _merge_quizzes(
    existing: list[GeneratedQuiz], result: QuizBackfillResult, missing: list[int]
) -> list[GeneratedQuiz]:
    """기존 quiz는 그대로 두고, 빠진 slide_idx만 보충본으로 채운다(중복·오염 방지)."""
    by_idx = {quiz.slide_idx: quiz for quiz in result.quizzes if quiz.slide_idx in set(missing)}
    merged = list(existing)
    for idx in missing:
        if idx in by_idx:
            merged.append(by_idx[idx])
    return merged


def _missing_indices(items: list[SlideIndexed], slide_count: int) -> list[int]:
    present = {item.slide_idx for item in items}
    return [idx for idx in range(slide_count) if idx not in present]


__all__ = ["backfill_missing"]
