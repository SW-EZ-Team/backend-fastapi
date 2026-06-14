"""강의(lessons) 생성 오케스트레이션 — Spring confirmCurriculum 이후 호출.

흐름: 커리큘럼 확정된 course의 모든 chapter(=curriculum_unit, lesson_id별)를 순회하며
기존 ChapterStudio 생성 파이프라인(load_generation_context → generate_chapter_state →
persist_chapter_state)을 적용하고, 각 강의 완료 시 public.chapter의 total_slides·status를
갱신해 Spring이 학습 가능 상태(AVAILABLE)를 조회할 수 있게 한다.

음성(TTS)은 플래그가 켜진 경우 그래프에서 즉시 생성하고, 아니면 queue 기반 후처리로 남긴다.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Protocol

from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.app.lesson_audio_backfill import backfill_lesson_audio
from app.modules.ChapterStudio_V1.app.pdf_context_injector import inject_reference_context_if_pdf
from app.modules.ChapterStudio_V1.common.config import tts_autogen_enabled
from app.modules.ChapterStudio_V1.common.errors import StorageError
from app.modules.ChapterStudio_V1.db.generation_context_loader import load_generation_context
from app.modules.ChapterStudio_V1.db.persistence import persist_chapter_state
from app.modules.ChapterStudio_V1.db.persistence_status import (
    mark_audio_backfill_pending,
    mark_chapter_failed,
    mark_chapter_progress,
    mark_chapter_running,
)
from app.modules.ChapterStudio_V1.db.weakness_aggregator import aggregate_weak_points
from app.modules.ChapterStudio_V1.pipeline.converters import state_to_response
from app.modules.ChapterStudio_V1.pipeline.graph import generate_chapter_state
from common.db import get_connection

_LOG = logging.getLogger(__name__)
_SPRING_COMMIT_RETRY_ATTEMPTS = 5
_SPRING_COMMIT_RETRY_DELAY_SEC = 1.0

# 노드 완료 → (완료 노드 수, 진행률%) 매핑 — persist 완료(100%)는 status_sql이 기록한다.
_NODE_PROGRESS: dict[str, tuple[int, int]] = {
    "prepare_context": (1, 10),
    "generate_lesson": (2, 55),
    "content_verify": (3, 70),
    "synthesize_audio": (4, 85),
    "postprocess_slides": (5, 95),
}
_TOTAL_NODES = 5
# GenerationContext.weak_points 필드 상한(max_length=240)과 동일하게 유지한다.
_WEAK_POINTS_MAX_CHARS = 240


class ExecuteConnection(Protocol):
    async def execute(self, query: str, *args: object) -> object:
        """상태 갱신 쿼리를 실행한다."""


def _chapter_id(lesson_id: str) -> str:
    """Spring public.chapter.id와 같은 키를 chapter_studio 저장 키로 사용한다."""
    return lesson_id


async def generate_lessons_for_course(course_id: str) -> None:
    """course의 모든 강의를 순차 생성한다. 강의별 실패는 격리하고 다음 강의로 진행한다."""
    lesson_ids = await _course_lesson_ids_after_spring_commit(course_id)
    if not lesson_ids:
        _LOG.error("[lessons] 생성할 chapter 없음 — courseId=%s", course_id)
        return

    _LOG.info("[lessons] 시작 — courseId=%s, 강의 %d개", course_id, len(lesson_ids))
    # 비용 통제 주석: Modal은 running 컨테이너 시간만 과금한다. 마지막 요청이 끝나면
    # scaledown_window(30초, deploy/modal_app.py)가 컨테이너를 자동 종료해 비용이 0이 된다.
    # un-deploy(modal app stop)는 배포 자체를 내리므로 여기서 호출하지 않는다.
    # decommission이 필요하면 CHAPTERSTUDIO_MODAL_TEARDOWN=true를 설정하고 수동 실행한다.
    done = 0
    for lesson_id in lesson_ids:
        if await _generate_one(course_id, lesson_id):
            done += 1
    _LOG.info("[lessons] 완료 — courseId=%s, 성공 %d/%d", course_id, done, len(lesson_ids))


async def _course_lesson_ids(course_id: str) -> list[str]:
    """public.chapter에서 강의 id를 order_index 순으로 읽는다 (= curriculum_unit.lesson_id)."""
    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT id FROM public.chapter WHERE course_id = $1 ORDER BY order_index",
            course_id,
        )
    return [row["id"] for row in rows]


async def _course_lesson_ids_after_spring_commit(course_id: str) -> list[str]:
    """Spring chapter INSERT 커밋 직후 호출되는 경우를 위해 빈 조회를 짧게 재확인한다."""
    for attempt in range(1, _SPRING_COMMIT_RETRY_ATTEMPTS + 1):
        lesson_ids = await _course_lesson_ids(course_id)
        if lesson_ids:
            return lesson_ids
        if attempt < _SPRING_COMMIT_RETRY_ATTEMPTS:
            _LOG.info(
                "[lessons] chapter 커밋 대기 — courseId=%s, retry=%d/%d",
                course_id,
                attempt,
                _SPRING_COMMIT_RETRY_ATTEMPTS,
            )
            await asyncio.sleep(_SPRING_COMMIT_RETRY_DELAY_SEC)
    return []


async def _generate_one(course_id: str, lesson_id: str) -> bool:
    """강의 1개를 생성·저장하고 public.chapter 상태를 AVAILABLE로 갱신한다.

    전체 코스 일괄 생성 경로에서도 단건 경로와 동일하게 이전 강의 약점을 주입한다.
    """
    try:
        weak_points = await _aggregate_weak_points_safely(course_id, lesson_id)
        context = await _load_generation_context_after_spring_commit(lesson_id)
        if context is None:
            _LOG.error("[lessons] 강의 생성 입력 없음 — lesson_id=%s", lesson_id)
            return False
        if weak_points:
            context = context.model_copy(update={"weak_points": weak_points})
        return await _generate_loaded_context(context)
    except Exception as exc:
        _LOG.error("[lessons] 강의 실패 — lesson_id=%s, stage=load_generation_context, error=%s", lesson_id, exc)
        return False


async def generate_lesson_for_chapter(
    course_id: str,
    lesson_id: str,
    *,
    audience_level: str | None = None,
    learning_goal: str | None = None,
    tone: int | None = None,
    pace: int | None = None,
    tutor_depth: int | None = None,
    socratic: int | None = None,
    use_formal_speech: bool | None = None,
    use_emoji: bool | None = None,
    tutor_name: str | None = None,
    tutor_tagline: str | None = None,
    is_default_tutor: bool | None = None,
    voice_sample_url: str | None = None,
) -> bool:
    """완료된 이전 강의 약점을 주입해 강의 1개를 progressive로 생성한다."""
    try:
        weak_points = await _aggregate_weak_points_safely(course_id, lesson_id)
        context = await _load_generation_context_after_spring_commit(lesson_id)
        if context is None:
            _LOG.error("[lessons] 단건 강의 생성 입력 없음 — courseId=%s, lessonId=%s", course_id, lesson_id)
            return False
        personalized = _personalized_context(
            context,
            weak_points=weak_points,
            audience_level=audience_level,
            learning_goal=learning_goal,
            tone=tone,
            pace=pace,
            tutor_depth=tutor_depth,
            socratic=socratic,
            use_formal_speech=use_formal_speech,
            use_emoji=use_emoji,
            tutor_name=tutor_name,
            tutor_tagline=tutor_tagline,
            is_default_tutor=is_default_tutor,
            voice_sample_url=voice_sample_url,
        )
        return await _generate_loaded_context(personalized)
    except Exception as exc:
        _LOG.error("[lessons] 단건 강의 실패 — courseId=%s, lessonId=%s, error=%s", course_id, lesson_id, exc)
        return False


async def _load_generation_context_after_spring_commit(lesson_id: str) -> GenerationContext | None:
    """Spring chapter/curriculum_unit 커밋 지연으로 인한 일시적 미조회 상태를 재확인한다."""
    for attempt in range(1, _SPRING_COMMIT_RETRY_ATTEMPTS + 1):
        context: GenerationContext | None = None
        async with get_connection() as conn:
            try:
                return await load_generation_context(conn, lesson_id)
            except StorageError:
                context = None
        if context is not None:
            return context
        if attempt < _SPRING_COMMIT_RETRY_ATTEMPTS:
            _LOG.info(
                "[lessons] 생성 입력 커밋 대기 — lessonId=%s, retry=%d/%d",
                lesson_id,
                attempt,
                _SPRING_COMMIT_RETRY_ATTEMPTS,
            )
            await asyncio.sleep(_SPRING_COMMIT_RETRY_DELAY_SEC)
    return None


async def _generate_loaded_context(context: GenerationContext) -> bool:
    """로드된 생성 컨텍스트를 공통 생성·저장 경로로 실행한다."""
    # PDF 소스 강의에서 참고도서 컨텍스트가 아직 없으면 Qdrant에서 자동 주입한다
    context = await inject_reference_context_if_pdf(context)
    chapter_id = _chapter_id(context.lesson_id)
    # 진단 우선: 무거운 생성에 들어가기 전에 진행중(running) 상태 행을 먼저 남긴다.
    # 단건·전체 코스 두 경로 모두 여기서 공통 처리한다(중간에 죽어도 running 행이 남는다).
    await _record_generation_running(context)
    stage = "generate_chapter_state"
    try:
        state = await generate_chapter_state(
            context.to_generation_input(),
            on_node_complete=_progress_recorder(context, chapter_id),
        )
        stage = "state_to_response"
        response = state_to_response(state, chapter_id)
        stage = "persist_chapter_state"
        async with get_connection() as conn:
            await persist_chapter_state(conn, context, chapter_id, state)
            await _mark_public_chapter_available(conn, context.lesson_id, len(response.slides))
        await _backfill_audio_when_needed(context)
        _LOG.info("[lessons] 강의 완료 — lesson_id=%s, 슬라이드 %d", context.lesson_id, len(response.slides))
        return True
    except Exception as exc:
        # 진단 우선: 실패 직전에 실제 예외 + 스택트레이스를 남겨 어느 stage에서 죽었는지 식별한다.
        # (상태 행만으로는 원인이 보이지 않아 조용한 실패가 됐던 부분을 가시화한다.)
        _LOG.exception("[lessons] 강의 생성 실패 — lessonId=%s, stage=%s", context.lesson_id, stage)
        await _record_generation_failure(context, chapter_id, stage, exc)
        return False


async def _aggregate_weak_points_safely(course_id: str, lesson_id: str) -> str:
    """이전 강의·모의고사 약점을 집계한다. 집계 실패가 강의 생성을 막지 않게 한다."""
    try:
        async with get_connection() as conn:
            weak_points = await aggregate_weak_points(conn, course_id, lesson_id)
    except Exception as exc:
        _LOG.warning("[lessons] 약점 집계 실패 — courseId=%s, lessonId=%s, error=%s", course_id, lesson_id, exc)
        return ""
    weak_points = weak_points.strip()[:_WEAK_POINTS_MAX_CHARS]
    if weak_points:
        # 운영 확인용: 약점이 실제 프롬프트에 반영되는 강의를 로그로 추적할 수 있게 한다.
        _LOG.info("[lessons] 약점 반영 — courseId=%s, lessonId=%s, weak_points=%s", course_id, lesson_id, weak_points)
    return weak_points


def _progress_recorder(context: GenerationContext, chapter_id: str):
    """노드 완료마다 진행률을 짧은 독립 커넥션으로 기록하는 콜백을 만든다.

    진행률 기록 실패가 생성 자체를 막아선 안 되므로 예외는 로그만 남기고 삼킨다.
    """

    async def record(node_name: str) -> None:
        progress = _NODE_PROGRESS.get(node_name)
        if progress is None:
            return
        completed_nodes, progress_percent = progress
        try:
            async with get_connection() as conn:
                await mark_chapter_progress(
                    conn,
                    context,
                    chapter_id,
                    current_node=node_name,
                    completed_nodes=completed_nodes,
                    total_nodes=_TOTAL_NODES,
                    progress_percent=progress_percent,
                )
            _LOG.info(
                "[lessons] 진행률 기록 — lessonId=%s, node=%s, %d%%",
                context.lesson_id,
                node_name,
                progress_percent,
            )
        except Exception:
            _LOG.exception("[lessons] 진행률 기록 실패 — lessonId=%s, node=%s", context.lesson_id, node_name)

    return record


async def _backfill_audio_when_needed(context: GenerationContext) -> None:
    """그래프 TTS가 꺼진 기본 배포에서 저장 후 음성을 채우되 강의 성공은 보존한다."""
    if tts_autogen_enabled():
        return
    try:
        result = await backfill_lesson_audio(context.lesson_id)
        _LOG.info("[lessons] 음성 백필 완료 — lesson_id=%s, result=%s", context.lesson_id, result)
        if _audio_backfill_failed(result):
            await _record_audio_pending(context, result)
    except Exception as exc:
        _LOG.warning("[lessons] 음성 백필 실패 — lesson_id=%s, error=%s", context.lesson_id, exc)
        await _record_audio_pending(context, {}, exc)


def _audio_backfill_failed(result: Mapping[str, object]) -> bool:
    failed = result.get("failed", 0)
    return isinstance(failed, int) and failed > 0


async def _record_audio_pending(
    context: GenerationContext,
    result: Mapping[str, object],
    error: Exception | None = None,
) -> None:
    try:
        async with get_connection() as conn:
            await mark_audio_backfill_pending(conn, context, result, error)
    except Exception as exc:
        _LOG.error("[lessons] 음성 백필 마커 기록 실패 — lesson_id=%s, error=%s", context.lesson_id, exc)


async def _mark_public_chapter_available(conn: ExecuteConnection, lesson_id: str, slide_count: int) -> None:
    await conn.execute(
        "UPDATE public.chapter SET total_slides = $2, status = 'AVAILABLE', updated_at = NOW() WHERE id = $1",
        lesson_id,
        slide_count,
    )


async def _record_generation_running(context: GenerationContext) -> None:
    """생성 시작 시 running 상태 행을 짧은 독립 트랜잭션으로 커밋한다(진행률 0% 고정 완화).

    이 행 기록 실패가 생성 자체를 막아선 안 되므로, 실패해도 로그만 남기고 진행한다.
    """
    chapter_id = _chapter_id(context.lesson_id)
    try:
        async with get_connection() as conn:
            await mark_chapter_running(conn, context, chapter_id)
        _LOG.info("[lessons] 생성 시작 상태 기록(running) — lessonId=%s", context.lesson_id)
    except Exception:
        _LOG.exception("[lessons] 생성 시작 상태 기록 실패 — lessonId=%s", context.lesson_id)


async def _record_generation_failure(context: GenerationContext, chapter_id: str, stage: str, exc: Exception) -> None:
    _LOG.error("[lessons] 강의 실패 — lesson_id=%s, stage=%s, error=%s", context.lesson_id, stage, exc)
    try:
        async with get_connection() as conn:
            await mark_chapter_failed(conn, context, chapter_id, stage, exc)
    except Exception:
        # 실패 상태 기록 자체가 또 실패하면 진짜 원인이 묻히므로 풀 스택으로 남긴다(삼키지 않음).
        _LOG.exception("[lessons] 실패 상태 기록 실패 — lessonId=%s, stage=%s", context.lesson_id, stage)


def _personalized_context(
    context: GenerationContext,
    *,
    weak_points: str,
    audience_level: str | None,
    learning_goal: str | None,
    tone: int | None,
    pace: int | None,
    tutor_depth: int | None,
    socratic: int | None,
    use_formal_speech: bool | None,
    use_emoji: bool | None,
    tutor_name: str | None,
    tutor_tagline: str | None,
    is_default_tutor: bool | None,
    voice_sample_url: str | None,
) -> GenerationContext:
    updates: dict[str, object] = {"weak_points": weak_points}
    if audience_level is not None:
        updates["audience_level"] = audience_level
    if learning_goal is not None:
        updates["learning_goal"] = learning_goal
    for key, value in {"tone": tone, "pace": pace, "tutor_depth": tutor_depth, "socratic": socratic}.items():
        if value is not None:
            updates[key] = value
    for key, value in {
        "use_formal_speech": use_formal_speech,
        "use_emoji": use_emoji,
        "tutor_name": tutor_name,
        "tutor_tagline": tutor_tagline,
        "is_default_tutor": is_default_tutor,
        "voice_sample_url": voice_sample_url,
    }.items():
        if value is not None:
            updates[key] = value
    return context.model_copy(update=updates)
