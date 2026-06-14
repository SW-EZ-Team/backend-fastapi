"""ChapterStudio LangGraph 파이프라인 조립."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import cast

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.modules.ChapterStudio_V1.app.generation_context import GenerationInput
from app.modules.ChapterStudio_V1.pipeline.converters import generation_input_to_initial_state, state_to_response
from app.modules.ChapterStudio_V1.pipeline.nodes.content_verify_node import content_verify_node
from app.modules.ChapterStudio_V1.pipeline.nodes.context_node import prepare_context_node
from app.modules.ChapterStudio_V1.pipeline.nodes.generate_node import generate_lesson_node
from app.modules.ChapterStudio_V1.pipeline.nodes.postprocess_node import postprocess_slides_node
from app.modules.ChapterStudio_V1.pipeline.nodes.synthesize_audio_node import synthesize_audio_node
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState
from app.modules.ChapterStudio_V1.schemas.response import ChapterResponse


def build_chapter_studio_graph() -> CompiledStateGraph:
    """강의 생성 StateGraph를 조립하고 컴파일한다."""
    graph = StateGraph(ChapterStudioState)
    graph.add_node("prepare_context", prepare_context_node)
    graph.add_node("generate_lesson", generate_lesson_node)
    graph.add_node("content_verify", content_verify_node)
    graph.add_node("synthesize_audio", synthesize_audio_node)
    graph.add_node("postprocess_slides", postprocess_slides_node)
    graph.set_entry_point("prepare_context")
    graph.add_edge("prepare_context", "generate_lesson")
    # 형식 repair → 내용 교정 → 깨끗해진 대본 기준 음성 합성 → 슬라이드 후처리 순.
    graph.add_edge("generate_lesson", "content_verify")
    graph.add_edge("content_verify", "synthesize_audio")
    graph.add_edge("synthesize_audio", "postprocess_slides")
    graph.add_edge("postprocess_slides", END)
    return graph.compile()


@lru_cache(maxsize=1)
def get_compiled_graph() -> CompiledStateGraph:
    """컴파일된 그래프 싱글톤을 반환한다."""
    return build_chapter_studio_graph()


# 노드 완료 콜백 타입 — 노드 이름 하나를 받아 진행률 기록 등 부수효과를 수행한다.
NodeCompleteCallback = Callable[[str], Awaitable[None]]


async def generate_chapter_state(
    generation_input: GenerationInput,
    on_node_complete: NodeCompleteCallback | None = None,
) -> ChapterStudioState:
    """DB generation_context 입력을 그래프에 태워 최종 상태를 반환한다.

    on_node_complete가 주어지면 astream으로 실행해 노드가 끝날 때마다 콜백을
    호출한다(진행률 기록용). 콜백이 없으면 기존 ainvoke 경로를 그대로 쓴다.
    """
    initial_state = generation_input_to_initial_state(generation_input)
    if on_node_complete is None:
        return cast(ChapterStudioState, await get_compiled_graph().ainvoke(initial_state))
    # updates 스트림으로 노드 완료 시점을 잡고, values 스트림의 마지막 항목이 최종 상태다.
    final_state: ChapterStudioState | None = None
    async for mode, chunk in get_compiled_graph().astream(
        initial_state, stream_mode=["updates", "values"]
    ):
        if mode == "updates" and isinstance(chunk, dict):
            for node_name in chunk:
                if isinstance(node_name, str) and not node_name.startswith("__"):
                    await on_node_complete(node_name)
        elif mode == "values":
            final_state = cast(ChapterStudioState, chunk)
    if final_state is None:
        raise RuntimeError("그래프 스트림이 최종 상태를 반환하지 않았다.")
    return final_state


async def generate_chapter_response(generation_input: GenerationInput, chapter_id: str) -> ChapterResponse:
    """DB generation_context 입력을 그래프에 태워 최종 응답 모델로 변환한다."""
    final_state = await generate_chapter_state(generation_input)
    return state_to_response(final_state, chapter_id)


__all__ = ["build_chapter_studio_graph", "generate_chapter_response", "generate_chapter_state", "get_compiled_graph"]
