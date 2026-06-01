"""Chat_V1 LangGraph StateGraph 조립 및 실행 진입점."""
from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.modules.Chat_V1.app.schemas import ChatRequest
from app.modules.Chat_V1.pipeline.nodes import (
    format_response,
    generate_answer,
    validate_input,
)
from app.modules.Chat_V1.pipeline.state import ChatState


def build_chat_graph() -> CompiledStateGraph:
    """Chat StateGraph를 조립하고 컴파일한다."""
    graph: StateGraph = StateGraph(ChatState)

    graph.add_node("validate_input", validate_input)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("format_response", format_response)

    graph.set_entry_point("validate_input")
    graph.add_edge("validate_input", "generate_answer")
    graph.add_edge("generate_answer", "format_response")
    graph.add_edge("format_response", END)

    return graph.compile()


@lru_cache(maxsize=1)
def get_compiled_graph() -> CompiledStateGraph:
    """컴파일된 그래프 싱글톤 — 앱 생명주기 동안 재사용한다."""
    return build_chat_graph()


async def run_chat_pipeline(request: ChatRequest) -> ChatState:
    """ChatRequest를 받아 파이프라인을 실행하고 최종 ChatState를 반환한다.

    서비스 레이어에서 request를 전달받아 초기 상태를 구성한 뒤
    그래프에 위임한다. build_system_prompt는 service.py에 있으므로
    순환 참조를 피하기 위해 service import만 지연한다.
    """
    from app.modules.Chat_V1.app.service import (
        build_lecture_keywords,
        build_system_prompt,
    )

    system_prompt = build_system_prompt(request)
    # 슬라이드 상한 검증·환각 가드에 쓸 메타를 컨텍스트에서 미리 뽑아 상태에 담는다.
    slide_count = len(request.lecture_context.slides)
    lecture_keywords = build_lecture_keywords(request)

    initial_state: ChatState = {
        "session_id": request.session_id,
        "user_message": request.user_message,
        "system_prompt": system_prompt,
        "slide_count": slide_count,
        "lecture_keywords": lecture_keywords,
        "error_message": None,
        "pipeline_status": "init",
    }

    graph = get_compiled_graph()
    final_state: ChatState = await graph.ainvoke(initial_state)
    return final_state
