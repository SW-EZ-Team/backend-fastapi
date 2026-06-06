"""채점 오케스트레이터 — 텍스트 채점 요청을 받아 Gemini 채점 후 Spring 콜백을 호출한다.

IN : GradeRequest
OUT: 없음 (채점 결과는 Spring 콜백으로 전달된다)

실패 시 Spring에 status=failed 콜백을 보내 submission이 영구 queued 상태로 남지 않도록 한다.
"""

from __future__ import annotations

import asyncio
import logging

from .config import get_grading_timeout_seconds
from .schemas import GradeRequest
from .spring_callback import SpringCallbackError, send_ai_result_callback
from .text_grader import TextGradingError, grade_text_submission

_LOG = logging.getLogger(__name__)


async def handle_text_grading_request(request: GradeRequest) -> None:
    """채점 전체 흐름을 비동기 컨텍스트에서 실행한다.

    동기 Gemini SDK 호출은 asyncio.to_thread로 이벤트 루프를 블록하지 않는다.
    """
    submission_id = request.submission_id
    _LOG.info("[GradingHandler] 채점 시작 | submissionId=%s", submission_id)

    try:
        timeout = get_grading_timeout_seconds()
        # Gemini 동기 채점을 스레드로 분리해 이벤트 루프 차단을 막는다
        result = await asyncio.to_thread(
            grade_text_submission,
            request.assignment_title,
            request.assignment_description,
            request.assignment_questions,
            request.answer_text,
            timeout,
        )
    except TextGradingError as exc:
        _LOG.error(
            "[GradingHandler] 텍스트 채점 실패 | submissionId=%s, error=%s",
            submission_id,
            exc,
        )
        _send_failed_callback(submission_id)
        return

    # 채점 성공 — Spring에 done 콜백을 전송한다
    try:
        await asyncio.to_thread(
            send_ai_result_callback,
            submission_id,
            result.score,
            result.feedback,
            result.ai_confidence,
            "done",
        )
    except SpringCallbackError as exc:
        _LOG.error(
            "[GradingHandler] Spring 콜백 전송 실패 | submissionId=%s, error=%s",
            submission_id,
            exc,
        )
        # 콜백 전송 실패는 채점 결과 유실이므로 재시도 없이 로그만 남긴다
        # (재시도 로직은 Spring 폴링 또는 운영 모니터링에서 처리한다)


def _send_failed_callback(submission_id: str) -> None:
    """채점 실패 시 Spring에 failed 콜백을 동기적으로 전송한다."""
    try:
        send_ai_result_callback(
            submission_id=submission_id,
            score=0,
            feedback="AI 채점 중 오류가 발생했습니다. 관리자에게 문의하세요.",
            ai_confidence=0.0,
            status_transition="failed",
        )
    except SpringCallbackError as exc:
        # failed 콜백마저 실패하면 로그만 남기고 진행한다
        _LOG.error(
            "[GradingHandler] failed 콜백 전송 실패 | submissionId=%s, error=%s",
            submission_id,
            exc,
        )
