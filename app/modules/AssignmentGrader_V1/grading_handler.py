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

# 콜백 재시도 정책 — 일시적 네트워크/Spring 재기동 구간에서 채점 결과 유실을 막는다.
_CALLBACK_MAX_ATTEMPTS = 3
_CALLBACK_BACKOFF_BASE_SEC = 1.0


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
        # 채점 실패도 Spring에 알려 submission이 영구 queued로 남지 않게 한다(재시도 포함)
        await _send_callback_with_retry(
            submission_id,
            score=0,
            feedback="AI 채점 중 오류가 발생했습니다. 관리자에게 문의하세요.",
            ai_confidence=0.0,
            status_transition="failed",
        )
        return

    # 채점 성공 — Spring에 done 콜백을 전송한다(일시 실패 대비 지수 백오프 재시도)
    await _send_callback_with_retry(
        submission_id,
        score=result.score,
        feedback=result.feedback,
        ai_confidence=result.ai_confidence,
        status_transition="done",
    )


async def _send_callback_with_retry(
    submission_id: str,
    *,
    score: int,
    feedback: str,
    ai_confidence: float,
    status_transition: str,
) -> bool:
    """Spring 콜백을 최대 3회(1s→2s→4s 백오프) 재시도한다.

    콜백 실패는 채점 결과 유실이므로 즉시 포기하지 않는다. 최종 실패 시에는
    로그만 남긴다(submission 복구는 Spring 폴링/운영 모니터링 책임).
    """
    for attempt in range(1, _CALLBACK_MAX_ATTEMPTS + 1):
        try:
            await asyncio.to_thread(
                send_ai_result_callback,
                submission_id,
                score,
                feedback,
                ai_confidence,
                status_transition,
            )
            return True
        except SpringCallbackError as exc:
            _LOG.warning(
                "[GradingHandler] Spring 콜백 실패 (%d/%d) | submissionId=%s, status=%s, error=%s",
                attempt,
                _CALLBACK_MAX_ATTEMPTS,
                submission_id,
                status_transition,
                exc,
            )
            if attempt < _CALLBACK_MAX_ATTEMPTS:
                await asyncio.sleep(_CALLBACK_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))
    _LOG.error(
        "[GradingHandler] Spring 콜백 최종 실패 — 채점 결과 미전달 | submissionId=%s, status=%s",
        submission_id,
        status_transition,
    )
    return False
