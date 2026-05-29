"""LangGraph 노드 함수 모음 — ASR 폴백 그래프의 실행 단위.

각 함수는 ASRState 를 받아 업데이트할 dict 를 반환한다 (LangGraph 관례).
asr_attempt_node 와 quality_check_node 는 async, 나머지는 sync 이다.
"""
from __future__ import annotations

import logging
import time
from typing import cast

from ai_connectors.errors import AIConnectorError

from .config import quality_pass_threshold
from .quality import aggregate_quality
from .state import ASRState, AttemptRecord

_LOG = logging.getLogger(__name__)


async def asr_attempt_node(state: ASRState) -> dict:
    """현재 tier 의 ASR 커넥터를 호출해 전사를 시도한다.

    성공 시 AttemptRecord 에 결과를 담고, 실패 시 quality_score=0.0 / text="" 로 기록한다.
    예외는 모두 catch 해 quality_reason 에 "error:{msg}" 형식으로 남긴다.
    """
    tier = state["current_tier"]
    factory = state["tier_factories"][tier]
    model_name = state["tier_model_names"][tier]

    t0 = time.perf_counter()
    try:
        connector = factory()
        response = await connector.generate(state["request"])
        latency_ms = (time.perf_counter() - t0) * 1000.0
        _LOG.info(
            "[tier %d] %s → \"%s...\" (%.0f ms)",
            tier,
            model_name,
            response.text[:60],
            latency_ms,
        )
        record: AttemptRecord = {
            "tier": tier,
            "model_name": model_name,
            "text": response.text,
            "latency_ms": latency_ms,
            "quality_score": 0.0,      # quality_check_node 에서 채워짐
            "quality_reason": "pending",
            "response": response,
        }
    except (AIConnectorError, OSError, ValueError, RuntimeError) as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        _LOG.warning("[tier %d] %s 실패: %s", tier, model_name, exc)
        record = {
            "tier": tier,
            "model_name": model_name,
            "text": "",
            "latency_ms": latency_ms,
            "quality_score": 0.0,
            "quality_reason": f"error:{exc}",
            "response": None,
        }

    return {"attempts": state["attempts"] + [record]}


def quality_check_node(state: ASRState) -> dict:
    """마지막 attempt 의 품질을 평가해 quality_score / quality_reason 을 갱신한다.

    response 가 None 인 에러 케이스는 점수를 0.0 으로 유지한다.
    성공 케이스는 aggregate_quality 를 호출해 휴리스틱 점수를 계산한다.
    """
    attempts = list(state["attempts"])
    # AttemptRecord(TypedDict) 를 수정 가능한 복사본으로 변환 후 품질 필드 갱신
    last: AttemptRecord = cast(AttemptRecord, dict(attempts[-1]))

    if last["response"] is not None:
        score, reason = aggregate_quality(
            last["text"],
            last["response"].duration_sec,
        )
        last["quality_score"] = score
        last["quality_reason"] = reason

    attempts[-1] = last
    return {"attempts": attempts}


def route_next_tier(state: ASRState) -> str:
    """품질 점수를 기반으로 다음 전환 경로를 결정한다.

    반환값은 graph.py 의 add_conditional_edges 라우트 키와 일치해야 한다:
      "done"      → 품질 통과, END 로 전환
      "exhausted" → tier 소진, best-effort 로 END 전환
      "retry"     → 다음 tier 로 재시도
    """
    last = state["attempts"][-1]
    score = last["quality_score"]
    threshold = quality_pass_threshold()

    if score >= threshold:
        _LOG.info("품질 통과 (tier %d, score=%.2f) — 종료", last["tier"], score)
        return "done"

    next_tier = state["current_tier"] + 1
    if next_tier >= len(state["tier_factories"]):
        _LOG.warning("모든 tier 소진 — best-effort 반환")
        return "exhausted"

    _LOG.info(
        "품질 미달 (score=%.2f, reason=%s) — tier %d 로 재시도",
        score,
        last["quality_reason"],
        next_tier,
    )
    return "retry"


def advance_tier_node(state: ASRState) -> dict:
    """current_tier 를 1 증가시켜 다음 tier 로 이동시킨다."""
    return {"current_tier": state["current_tier"] + 1}
