"""ExamForge LangGraph 파이프라인 조립."""
from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .state import ExamForgeState
from .nodes.parse_source_node import parse_source_node
from .nodes.plan_exam_node import plan_exam_node
from .nodes.generate_questions_node import generate_questions_node
from .nodes.generate_distractors_node import generate_distractors_node
from .nodes.generate_answers_node import generate_answers_node
from .nodes.verify_answers_node import verify_answers_node
from .nodes.validate_node import validate_node
from .nodes.retry_router_node import retry_router_node, route_after_validation
from .nodes.calibrate_difficulty_node import calibrate_difficulty_node
from .nodes.format_output_node import format_output_node


def build_exam_forge_graph() -> CompiledStateGraph:
    """ExamForge StateGraph를 조립하고 컴파일한다."""
    graph = StateGraph(ExamForgeState)

    graph.add_node("parse_source", parse_source_node)
    graph.add_node("plan_exam", plan_exam_node)
    graph.add_node("generate_questions", generate_questions_node)
    graph.add_node("generate_distractors", generate_distractors_node)
    graph.add_node("generate_answers", generate_answers_node)
    graph.add_node("verify_answers", verify_answers_node)
    graph.add_node("validate", validate_node)
    graph.add_node("retry_router", retry_router_node)
    graph.add_node("calibrate_difficulty", calibrate_difficulty_node)
    graph.add_node("format_output", format_output_node)

    graph.set_entry_point("parse_source")

    graph.add_edge("parse_source", "plan_exam")
    graph.add_edge("plan_exam", "generate_questions")
    graph.add_edge("generate_questions", "generate_distractors")
    graph.add_edge("generate_distractors", "generate_answers")
    graph.add_edge("generate_answers", "verify_answers")
    graph.add_edge("verify_answers", "validate")
    graph.add_edge("validate", "retry_router")

    graph.add_conditional_edges(
        "retry_router",
        route_after_validation,
        {
            "passed": "calibrate_difficulty",
            "retry": "generate_questions",
            "exhausted": "calibrate_difficulty",
        },
    )

    graph.add_edge("calibrate_difficulty", "format_output")
    graph.add_edge("format_output", END)

    return graph.compile()


@lru_cache(maxsize=1)
def get_compiled_graph() -> CompiledStateGraph:
    """컴파일된 그래프 싱글톤."""
    return build_exam_forge_graph()
