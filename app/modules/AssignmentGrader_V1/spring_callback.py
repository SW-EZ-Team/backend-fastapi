"""Spring 콜백 원자적 모듈 — 채점 결과를 Spring /internal/submissions/{id}/ai-result 로 전달한다.

IN : submission_id, score, feedback, ai_confidence, status_transition
OUT: 없음 (실패 시 SpringCallbackError raise)
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal

from .config import get_internal_token, get_spring_base_url, get_spring_callback_timeout_seconds

_LOG = logging.getLogger(__name__)


class SpringCallbackError(RuntimeError):
    """Spring 콜백 전송 실패를 정규화한다."""


def send_ai_result_callback(
    submission_id: str,
    score: int,
    feedback: str,
    ai_confidence: float,
    status_transition: str = "done",
) -> None:
    """Spring /internal/submissions/{id}/ai-result 로 채점 결과를 동기 HTTP POST 한다.

    Spring AiResultCallbackRequest 스펙 필드:
      - score, feedback, aiConfidence: 채점 결과
      - statusTransition: done | failed | grading | queued
      - ocrText, ocrFailedPages, totalPages, isRetry: 텍스트 채점에서는 미사용(null/0)
    """
    base_url = get_spring_base_url()
    token = get_internal_token()
    timeout = get_spring_callback_timeout_seconds()

    url = f"{base_url}/internal/submissions/{submission_id}/ai-result"

    # aiConfidence는 BigDecimal(precision=4, scale=3) — 소수점 3자리로 반올림한다
    confidence_str = str(round(Decimal(str(ai_confidence)), 3))

    payload = {
        "score": score,
        "feedback": feedback,
        "aiConfidence": float(confidence_str),
        "statusTransition": status_transition,
        # 텍스트 채점에서 OCR 관련 필드는 사용하지 않는다
        "ocrText": None,
        "ocrFailedPages": 0,
        "totalPages": None,
        "isRetry": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            # Spring InternalTokenFilter가 검증하는 내부 인증 헤더
            "X-Internal-Token": token,
        },
        method="POST",
    )

    _LOG.info(
        "[SpringCallback] 채점 결과 콜백 전송 | submissionId=%s, score=%d, status=%s",
        submission_id,
        score,
        status_transition,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            _ = response.read()
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")[:300]
        raise SpringCallbackError(
            f"Spring 콜백 HTTP 오류 (status={exc.code}): {raw_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SpringCallbackError(f"Spring 콜백 연결 실패: {exc.reason}") from exc

    _LOG.info("[SpringCallback] 콜백 전송 완료 | submissionId=%s", submission_id)
