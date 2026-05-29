"""LangGraph 파이프라인 그래프 빌더 — 8개 Stage 노드를 조립해 컴파일된 그래프를 반환한다.

그래프 구조:
  START → classify_pdf → extract_base → llm_correct → quality_gate
                                                          │
                                               route_after_quality()
                                              ╱         │         ╲
                                       "pass"     "partial"    "fail_all"
                                         │            │            │
                                         │       fallback          │
                                         │            │            │
                                         ▼            ▼            ▼
                                      postprocess ←──────────────
                                         │
                                      chunk_node
                                         │
                                     embed_store
                                         │
                                        END

품질 게이트 라우팅:
- "pass"     : 전 페이지 통과 → 폴백 건너뜀, postprocess 로 직행
- "partial"  : 일부 실패 → fallback 재추출 후 postprocess
- "fail_all" : 전 페이지 실패 → 최선 결과로 postprocess 진행
"""
from __future__ import annotations

import logging

_LOG = logging.getLogger(__name__)

# 컴파일된 그래프를 캐싱해 반복 호출 시 재컴파일 오버헤드를 방지한다
# dict 홀더 패턴 — PLW0603(global 문) 경고 없이 모듈 레벨 캐시를 구현한다
_CACHE: dict[str, object] = {}


def get_compiled_graph() -> object:
    """컴파일된 LangGraph 그래프를 반환한다.

    첫 호출 시 그래프를 빌드·컴파일하고 이후에는 캐싱된 인스턴스를 반환한다.
    """
    if _CACHE.get("graph") is not None:
        return _CACHE["graph"]

    from langgraph.graph import END, START, StateGraph

    from ..schemas.state import OCRPipelineState
    from .nodes import (
        chunk_node,
        classify_pdf,
        embed_store,
        extract_base,
        fallback,
        llm_correct,
        postprocess,
        quality_gate,
        route_after_quality,
    )

    builder = StateGraph(OCRPipelineState)

    # --- 노드 등록 ---
    builder.add_node("classify_pdf", classify_pdf)
    builder.add_node("extract_base", extract_base)
    builder.add_node("llm_correct", llm_correct)
    builder.add_node("quality_gate", quality_gate)
    builder.add_node("fallback", fallback)
    builder.add_node("postprocess", postprocess)
    builder.add_node("chunk_node", chunk_node)
    builder.add_node("embed_store", embed_store)

    # --- 선형 엣지 ---
    builder.add_edge(START, "classify_pdf")
    builder.add_edge("classify_pdf", "extract_base")
    builder.add_edge("extract_base", "llm_correct")
    builder.add_edge("llm_correct", "quality_gate")

    # --- 품질 게이트 조건부 엣지 ---
    builder.add_conditional_edges(
        "quality_gate",
        route_after_quality,
        {
            "pass": "postprocess",
            "partial": "fallback",
            "fail_all": "postprocess",
        },
    )

    # 폴백 완료 후 후처리로 합류
    builder.add_edge("fallback", "postprocess")

    # --- 후처리 → 청킹 → 임베딩·저장 → 종료 ---
    builder.add_edge("postprocess", "chunk_node")
    builder.add_edge("chunk_node", "embed_store")
    builder.add_edge("embed_store", END)

    _CACHE["graph"] = builder.compile()
    _LOG.info("LangGraph OCR 파이프라인 그래프 컴파일 완료")
    return _CACHE["graph"]
