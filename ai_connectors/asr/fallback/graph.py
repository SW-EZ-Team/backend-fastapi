"""LangGraph StateGraph 조립 모듈.

build_fallback_graph() 가 그래프를 조립하고 compile() 해 반환한다.
get_compiled_graph() 는 lru_cache 로 싱글톤을 보장한다 — StateGraph.compile() 은
재사용 가능한 실행 객체를 반환하므로 한 번만 조립하면 된다.
"""
from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, StateGraph

from .nodes import advance_tier_node, asr_attempt_node, quality_check_node, route_next_tier
from .state import ASRState


def build_fallback_graph():
    """폴백 ASR StateGraph 를 조립하고 compile 해 반환한다.

    실행 흐름:
      asr_attempt → quality_check → [route]
        "done"      → END (품질 통과)
        "exhausted" → END (tier 소진, best-effort)
        "retry"     → advance_tier → asr_attempt (루프)
    """
    graph: StateGraph = StateGraph(ASRState)

    # 노드 등록
    graph.add_node("asr_attempt", asr_attempt_node)
    graph.add_node("quality_check", quality_check_node)
    graph.add_node("advance_tier", advance_tier_node)

    # 진입점
    graph.set_entry_point("asr_attempt")

    # 고정 엣지
    graph.add_edge("asr_attempt", "quality_check")
    graph.add_edge("advance_tier", "asr_attempt")

    # 조건부 엣지 — route_next_tier 가 반환하는 문자열로 분기
    graph.add_conditional_edges(
        "quality_check",
        route_next_tier,
        {
            "done": END,
            "exhausted": END,
            "retry": "advance_tier",
        },
    )

    return graph.compile()


@lru_cache(maxsize=1)
def get_compiled_graph():
    """컴파일된 그래프 싱글톤을 반환한다.

    lru_cache(maxsize=1) 로 프로세스 수명 동안 단 한 번만 조립한다.
    StateGraph.compile() 결과물은 상태를 가지지 않으므로 여러 요청에서 공유 가능하다.
    """
    return build_fallback_graph()
