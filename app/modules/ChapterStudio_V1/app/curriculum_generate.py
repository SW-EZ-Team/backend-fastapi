"""커리큘럼 생성 오케스트레이션 — plan-first 원칙.

Spring POST /api/curriculum/generate 수신 후 백그라운드에서 실행된다.
흐름:
  1. blueprint(결정적) — N개 슬롯·단계·주제범위·역할을 AI 없이 확정
  2. 슬롯-루프 오더 — 각 슬롯의 텍스트(title/summary/learning_goal/key_topics)만 AI에 요청
  3. Pydantic strict 검증 + 슬롯 수 == N 강제
  4. persist_curriculum — DB 저장

AI는 고정 슬롯 안의 텍스트만 채운다.
챕터 개수·순서·단계역할·주제범위는 블루프린트가 결정하며 AI가 바꿀 수 없다.
DB 쓰기는 schema-qualified 명시(get_connection은 search_path 미설정).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.ChapterStudio_V1.ai_connectors.registry import get_planner_connector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.app.curriculum_blueprint import (
    ChapterSlot,
    build_curriculum_blueprint,
)
from app.modules.ChapterStudio_V1.common.config import active_planner_model
from app.modules.ChapterStudio_V1.db.curriculum_persistence import persist_curriculum
from common.db import get_connection

_LOG = logging.getLogger(__name__)

# Codex CLI용 운영 경로 output-schema 경로
_GEN_SCHEMA_PATH = Path(__file__).with_name("codex_curriculum_generate.schema.json")

_PLANNER_SYSTEM = (
    "너는 한국어 AI 과외 커리큘럼 설계자다. "
    "주어진 슬롯 명세에 따라 각 슬롯의 title·summary·learning_goal·key_topics 문구만 한국어로 채운다. "
    "슬롯 개수·순서·단계역할·주제범위는 이미 확정되어 있으므로 절대 변경하지 않는다. "
    "반드시 JSON 배열만 출력하고, 설명·코드펜스·생각과정은 절대 출력하지 않는다."
)

# <think>...</think> 추론 블록 제거용 (Qwen3 thinking 출력 대비)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_SPRING_COMMIT_RETRY_ATTEMPTS = 5
_SPRING_COMMIT_RETRY_DELAY_SEC = 1.0
_COURSE_FAILED_STATUS = "CURRICULUM_FAILED"


# ---------------------------------------------------------------------------
# 운영용 슬롯 응답 Pydantic 모델 — AI 출력을 strict하게 검증한다
# ---------------------------------------------------------------------------


class _SlotResponse(BaseModel):
    """AI가 채운 단일 슬롯 텍스트 응답이다."""

    model_config = ConfigDict(strict=True, frozen=True)

    order: int = Field(ge=1, le=30)
    stage: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=300)
    learning_goal: str = Field(min_length=1, max_length=200)
    key_topics: list[str] = Field(min_length=3, max_length=5)


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------


async def generate_and_store_curriculum(
    course_id: str,
    subject: str,
    lesson_count: int,
    source_type: str,
) -> None:
    """커리큘럼을 생성·저장하고 실패 시 course 상태를 실패로 전이한다."""
    try:
        course = await _load_course_after_spring_commit(course_id)
        if course is None:
            _LOG.error("[curriculum] course 없음 — courseId=%s", course_id)
            await mark_course_curriculum_failed(course_id, "course not found")
            return

        n = max(1, lesson_count)
        lessons = await _plan_with_blueprint(course, subject, n)
        if not lessons:
            _LOG.error("[curriculum] planner가 유효한 강의를 만들지 못함 — courseId=%s", course_id)
            await mark_course_curriculum_failed(course_id, "planner returned empty lessons")
            return

        async with get_connection() as conn:
            saved = await persist_curriculum(
                conn, course=course, lessons=lessons, planner_model=active_planner_model()
            )
        _LOG.info("[curriculum] 저장 완료 — courseId=%s, 강의 %d개", course_id, saved)
    except Exception as exc:
        _LOG.error("[curriculum] 생성 실패 — courseId=%s, error=%s", course_id, exc, exc_info=True)
        await mark_course_curriculum_failed(course_id, str(exc))


async def mark_course_curriculum_failed(course_id: str, reason: str) -> None:
    """침묵 실패를 막기 위해 public.course 상태를 실패로 전이한다."""
    try:
        async with get_connection() as conn:
            await conn.execute(
                "UPDATE public.course SET status = $2, updated_at = NOW() WHERE id = $1",
                course_id,
                _COURSE_FAILED_STATUS,
            )
    except Exception as exc:
        _LOG.error(
            "[curriculum] 실패 상태 기록 실패 — courseId=%s, reason=%s, error=%s",
            course_id,
            reason,
            exc,
        )


# ---------------------------------------------------------------------------
# plan-first 핵심 흐름: 블루프린트 → 슬롯-루프 → 검증
# ---------------------------------------------------------------------------


async def _plan_with_blueprint(
    course: dict,
    subject: str,
    lesson_count: int,
) -> list[dict]:
    """블루프린트 기반 plan-first 생성 흐름이다.

    1. 결정적 블루프린트 생성 (AI 없음)
    2. 전체 슬롯을 한 번에 AI에 요청 (슬롯별 텍스트만)
    3. 결정적 검증: 수 == N, 슬롯 1:1 정합, Pydantic strict
    4. N 미달 시 부족 슬롯만 재요청 (최대 1회)
    """
    topic = course.get("topic_text") or course.get("course_name") or subject or "학습 주제"
    subject_name = course.get("subject") or subject or "일반"

    # 블루프린트 생성 — AI 없이 결정적으로 N개 슬롯 확정
    blueprint = build_curriculum_blueprint(
        subject=subject_name,
        lesson_count=lesson_count,
    )

    connector = get_planner_connector()
    prompt = _build_slot_loop_prompt(topic, subject_name, blueprint)
    req = ChapterAIRequest(
        system=_PLANNER_SYSTEM,
        user=prompt,
        max_tokens=8000,
        temperature=0.2,
        extra=_codex_schema_extra(),
    )
    resp = await connector.generate(req)
    slot_responses = _parse_and_validate(resp.text, blueprint)

    # N 미달 시 부족 슬롯만 재요청 (1회 한도)
    if len(slot_responses) < lesson_count:
        slot_responses = await _repair_missing_slots(
            connector, topic, subject_name, blueprint, slot_responses
        )

    # 재요청 후에도 N 미달이면 명시 실패
    if len(slot_responses) < lesson_count:
        missing = lesson_count - len(slot_responses)
        raise ValueError(
            f"블루프린트 N={lesson_count}개 요구 중 {missing}개 슬롯 미충족 — "
            "AI 응답이 지속적으로 슬롯 수를 맞추지 못했다."
        )

    return [_slot_response_to_lesson(sr, blueprint[sr.order - 1]) for sr in slot_responses]


def _build_slot_loop_prompt(
    topic: str,
    subject: str,
    blueprint: list[ChapterSlot],
) -> str:
    """각 슬롯의 명세를 나열하고 텍스트 채우기를 지시하는 프롬프트를 생성한다.

    AI에게 전달하는 내용:
    - 슬롯마다 order/stage/topic_scope/role이 고정되어 있음을 명시
    - 채울 항목: title, summary, learning_goal, key_topics만
    - 구조 변경 금지 명령
    """
    n = len(blueprint)
    slot_lines = "\n".join(
        f'  {{"order":{s.order},"stage":"{s.stage}",'
        f'"topic_scope":"{s.topic_scope}","role":"{s.role}"}}'
        for s in blueprint
    )
    return (
        "/no_think\n"
        f"과외 커리큘럼 텍스트 채우기 작업이다.\n"
        f"주제: {topic}\n과목: {subject}\n전체 강의 수: {n}개 (고정, 변경 불가)\n\n"
        f"아래 {n}개 슬롯의 order·stage·topic_scope·role은 이미 결정되어 있다.\n"
        "각 슬롯에 대해 title·summary·learning_goal·key_topics(3~5개)만 한국어로 채워라.\n"
        "슬롯 수·순서·stage·topic_scope는 절대 변경하지 마라.\n\n"
        f"슬롯 명세:\n{slot_lines}\n\n"
        "출력 형식 (JSON 배열만, 다른 텍스트·코드펜스 금지):\n"
        '[{"order":1,"stage":"관점 잡기","title":"제목","summary":"한 문장 요약",'
        '"learning_goal":"학습 목표","key_topics":["키1","키2","키3"]}, ...]\n\n'
        f"규칙: 배열 길이 정확히 {n}개. order는 1~{n} 연속. "
        "key_topics 3~5개. title 120자 이내. summary 300자 이내. "
        "learning_goal 200자 이내. 모든 텍스트는 한국어."
    )


def _codex_schema_extra() -> dict[str, str]:
    """Codex CLI 커넥터에 output-schema 경로를 전달한다.

    [중요] 기본 planner는 opus46(ACTIVE_PLANNER_MODEL 기본값)이며, 이 경로에서는
    output-schema 파일이 no-op이다 — Anthropic 커넥터는 extra의 output_schema_path를
    읽지 않기 때문이다. 따라서 opus46 경로의 유일한 안전망은 _parse_and_validate의
    Pydantic strict 검증 + 슬롯 1:1 정합 게이트다. codex_cli 커넥터를 쓸 때만
    이 스키마가 추가 방어층으로 작동한다.
    """
    if _GEN_SCHEMA_PATH.exists():
        return {"output_schema_path": str(_GEN_SCHEMA_PATH)}
    return {}


def _parse_and_validate(
    raw: str,
    blueprint: list[ChapterSlot],
) -> list[_SlotResponse]:
    """AI 출력을 Pydantic strict로 검증하고 블루프린트 슬롯과 1:1 정합을 확인한다.

    기존 substring best-effort 방식 대신 엄격한 파싱을 적용한다.
    슬롯 정합 실패(order/stage 불일치)는 해당 슬롯을 결과에서 제외한다.
    """
    text = _THINK_RE.sub("", raw).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        _LOG.error("[curriculum] JSON 배열을 찾지 못함: %r", text[:300])
        return []

    try:
        raw_items = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        _LOG.error("[curriculum] JSON 파싱 실패: %s | %r", exc, text[start : start + 300])
        return []

    if not isinstance(raw_items, list):
        return []

    # 블루프린트 인덱스 맵 (order → ChapterSlot) — 1:1 정합 검사에 사용
    bp_map: dict[int, ChapterSlot] = {s.order: s for s in blueprint}
    validated: list[_SlotResponse] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            sr = _SlotResponse.model_validate(item)
        except ValidationError as exc:
            _LOG.warning("[curriculum] 슬롯 Pydantic 검증 실패 (order=%s): %s", item.get("order"), exc)
            continue

        # 슬롯 정합: AI가 반환한 stage가 블루프린트 슬롯의 stage와 일치해야 한다
        expected_slot = bp_map.get(sr.order)
        if expected_slot is None:
            _LOG.warning("[curriculum] 블루프린트에 없는 order=%d 슬롯 무시", sr.order)
            continue
        if sr.stage != expected_slot.stage:
            _LOG.warning(
                "[curriculum] stage 불일치 슬롯 제외 — order=%d, 기대=%s, 수신=%s",
                sr.order,
                expected_slot.stage,
                sr.stage,
            )
            continue

        validated.append(sr)

    # order 기준 정렬 및 중복 제거 (동일 order 중 첫 번째만 유지)
    seen_orders: set[int] = set()
    deduped: list[_SlotResponse] = []
    for sr in sorted(validated, key=lambda x: x.order):
        if sr.order not in seen_orders:
            seen_orders.add(sr.order)
            deduped.append(sr)

    return deduped


async def _repair_missing_slots(
    connector: object,
    topic: str,
    subject: str,
    blueprint: list[ChapterSlot],
    received: list[_SlotResponse],
) -> list[_SlotResponse]:
    """N 미달 시 부족한 슬롯만 재요청한다 (최대 1회).

    부족 슬롯의 블루프린트 명세만 재전달해 최소 AI 호출로 복구를 시도한다.
    """
    received_orders = {sr.order for sr in received}
    missing_slots = [s for s in blueprint if s.order not in received_orders]

    if not missing_slots:
        return received

    _LOG.warning(
        "[curriculum] 슬롯 미달 — 부족 슬롯 재요청: %s",
        [s.order for s in missing_slots],
    )

    repair_prompt = _build_slot_loop_prompt(topic, subject, missing_slots)
    req = ChapterAIRequest(
        system=_PLANNER_SYSTEM,
        user=repair_prompt,
        max_tokens=4000,
        temperature=0.15,
        extra=_codex_schema_extra(),
    )
    from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector

    if not isinstance(connector, AIConnector):
        return received

    resp = await connector.generate(req)
    repaired = _parse_and_validate(resp.text, missing_slots)

    merged = list(received) + repaired
    merged.sort(key=lambda x: x.order)
    # 중복 제거 (재요청과 기존 응답이 겹치는 경우 방어)
    seen: set[int] = set()
    result: list[_SlotResponse] = []
    for sr in merged:
        if sr.order not in seen:
            seen.add(sr.order)
            result.append(sr)
    return result


def _slot_response_to_lesson(
    sr: _SlotResponse,
    slot: ChapterSlot,
) -> dict:
    """_SlotResponse + ChapterSlot을 persist_curriculum이 기대하는 dict로 변환한다.

    블루프린트에서 결정된 slide_count·estimated_minutes를 우선 사용하고
    key_topics는 AI가 채운 문구를 사용한다 (3~5개 범위 clamp).
    """
    key_topics = list(sr.key_topics)[:5]
    if len(key_topics) < 3:
        # key_topics가 3개 미만이면 블루프린트 힌트로 보충 (재현성 유지)
        hints = slot.key_topics[: 3 - len(key_topics)]
        key_topics = key_topics + hints

    return {
        "order": sr.order,
        "title": sr.title,
        "description": sr.summary,
        # slide_count는 블루프린트(slide_count_from_minutes)에서 결정된 값이다(AI 미관여).
        "slide_count": _clamp_int(slot.slide_count, 12, 10, 15),
        "estimated_minutes": _clamp_int(slot.estimated_minutes, 30, 20, 60),
        "learning_goal": sr.learning_goal,
        "key_topics": key_topics,
    }


# ---------------------------------------------------------------------------
# DB 조회 헬퍼
# ---------------------------------------------------------------------------


async def _load_course_after_spring_commit(course_id: str) -> dict | None:
    """Spring course INSERT 커밋 직후 호출되는 경우를 위해 짧게 재조회한다."""
    for attempt in range(1, _SPRING_COMMIT_RETRY_ATTEMPTS + 1):
        course = await _load_course(course_id)
        if course is not None:
            return course
        if attempt < _SPRING_COMMIT_RETRY_ATTEMPTS:
            _LOG.info(
                "[curriculum] course 커밋 대기 — courseId=%s, retry=%d/%d",
                course_id,
                attempt,
                _SPRING_COMMIT_RETRY_ATTEMPTS,
            )
            await asyncio.sleep(_SPRING_COMMIT_RETRY_DELAY_SEC)
    return None


async def _load_course(course_id: str) -> dict | None:
    """public.course에서 커리큘럼 생성에 필요한 메타를 읽는다."""
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, course_name, subject, source_type, source_pdf_url, topic_text "
            "FROM public.course WHERE id = $1",
            course_id,
        )
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _clamp_int(value: object, default: int, low: int, high: int) -> int:
    """정수로 변환하고 [low, high] 범위로 제한한다."""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(low, min(high, n))
