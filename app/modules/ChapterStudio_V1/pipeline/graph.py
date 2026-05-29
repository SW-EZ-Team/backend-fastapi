"""ChapterStudio LangGraph 파이프라인 조립."""
from __future__ import annotations

from functools import lru_cache
from typing import cast

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.modules.ChapterStudio_V1.app.generation_context import GenerationInput
from app.modules.ChapterStudio_V1.pipeline.converters import generation_input_to_initial_state, state_to_response
from app.modules.ChapterStudio_V1.pipeline.nodes.context_node import prepare_context_node
from app.modules.ChapterStudio_V1.pipeline.nodes.generate_node import generate_lesson_node
from app.modules.ChapterStudio_V1.pipeline.nodes.postprocess_node import postprocess_slides_node
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState
from app.modules.ChapterStudio_V1.schemas.response import ChapterResponse


def build_chapter_studio_graph() -> CompiledStateGraph:
    """강의 생성 StateGraph를 조립하고 컴파일한다."""
    graph = StateGraph(ChapterStudioState)
    graph.add_node("prepare_context", prepare_context_node)
    graph.add_node("generate_lesson", generate_lesson_node)
    graph.add_node("postprocess_slides", postprocess_slides_node)
    graph.set_entry_point("prepare_context")
    graph.add_edge("prepare_context", "generate_lesson")
    graph.add_edge("generate_lesson", "postprocess_slides")
    graph.add_edge("postprocess_slides", END)
    return graph.compile()


@lru_cache(maxsize=1)
def get_compiled_graph() -> CompiledStateGraph:
    """컴파일된 그래프 싱글톤을 반환한다."""
    return build_chapter_studio_graph()


async def generate_chapter_state(generation_input: GenerationInput) -> ChapterStudioState:
    """DB generation_context 입력을 그래프에 태워 최종 상태를 반환한다."""
    return cast(
        ChapterStudioState,
        await get_compiled_graph().ainvoke(generation_input_to_initial_state(generation_input)),
    )


async def generate_chapter_response(generation_input: GenerationInput, chapter_id: str) -> ChapterResponse:
    """DB generation_context 입력을 그래프에 태워 최종 응답 모델로 변환한다."""
    final_state = await generate_chapter_state(generation_input)
    return state_to_response(final_state, chapter_id)


__all__ = ["build_chapter_studio_graph", "generate_chapter_response", "generate_chapter_state", "get_compiled_graph"]
