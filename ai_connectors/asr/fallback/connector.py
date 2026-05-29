"""FallbackASRConnector — LangGraph 기반 2단 폴백 ASR 커넥터.

ASRConnector Protocol 을 구현해 호출부 변경 없이 교체 가능하다.
내부적으로 LangGraph StateGraph 가 tier 0 → 1 → 2 순으로 품질 검사를
수행하고, 통과한 첫 결과를 반환한다. 전 tier 실패 시 최고 점수 응답을
best-effort 로 반환하며, 응답 자체가 없으면 AIConnectorError 를 raise 한다.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from ai_connectors.errors import AIConnectorError
from ai_connectors.schemas import ASRRequest, ASRResponse

from .graph import get_compiled_graph
from .state import ASRState

_LOG = logging.getLogger(__name__)


class FallbackASRConnector:
    """LangGraph 기반 폴백 ASR 커넥터.

    tier_factories[i]() 는 i 번째 tier 의 ASRConnector 를 반환해야 한다.
    생성 시 커넥터를 즉시 로드하지 않고 factory 로 주입받는 이유:
    콜드스타트 비용을 실제 tier 진입 시점에만 지불하기 위함이다.
    """

    name: str = "asr-fallback"

    def __init__(
        self,
        tier_factories: list[Callable[[], Any]],
        tier_model_names: list[str],
    ) -> None:
        """tier_factories 와 tier_model_names 는 동일 인덱스로 대응해야 한다."""
        if len(tier_factories) != len(tier_model_names):
            raise ValueError("tier_factories 와 tier_model_names 길이 불일치")
        if not tier_factories:
            raise ValueError("tier_factories 비어 있음 — 최소 1개 필요")
        self._tier_factories = tier_factories
        self._tier_model_names = tier_model_names
        self._graph = get_compiled_graph()

    async def generate(self, request: ASRRequest) -> ASRResponse:
        """ASR 요청을 폴백 그래프에 위임해 최적 결과를 반환한다."""
        initial: ASRState = {
            "request": request,
            "tier_factories": self._tier_factories,
            "tier_model_names": self._tier_model_names,
            "current_tier": 0,
            "attempts": [],
            "done": False,
        }
        final_state = await self._graph.ainvoke(initial)
        return self._pick_best_response(final_state)

    def _pick_best_response(self, state: ASRState) -> ASRResponse:
        """품질체크 통과 attempt 우선, 없으면 quality_score 최고값을 반환한다.

        응답이 있는 attempt 가 하나도 없으면 AIConnectorError 를 raise 한다.
        """
        attempts = state["attempts"]
        if not attempts:
            raise AIConnectorError("모든 tier attempts 실패 — 결과 없음")

        # response 가 None 이 아닌 attempt (= 에러 없이 전사 완료한 것) 만 후보
        ok = [a for a in attempts if a["response"] is not None]
        if not ok:
            failures = "; ".join(
                f"tier{a['tier']}:{a['quality_reason']}" for a in attempts
            )
            raise AIConnectorError(f"모든 tier 실패: {failures}")

        # quality_score 최고값 채택 — 품질 통과 attempt 가 있으면 자연스럽게 선택됨
        best = max(ok, key=lambda a: a["quality_score"])
        _LOG.info(
            "폴백 완료 — tier %d (%s) 채택, score=%.2f, 시도 %d회",
            best["tier"],
            best["model_name"],
            best["quality_score"],
            len(attempts),
        )
        return best["response"]

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그."""
        return feature in {"transcription", "language_hint", "fallback"}
