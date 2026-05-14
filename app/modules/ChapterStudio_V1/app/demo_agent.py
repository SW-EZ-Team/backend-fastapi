from __future__ import annotations

import asyncio
from functools import cache
from typing import Literal, Protocol, TypedDict, cast

from langgraph.graph import END, StateGraph

from app.modules.ChapterStudio_V1.app.codex_demo_pipeline import build_codex_demo_result
from app.modules.ChapterStudio_V1.app.demo_pipeline import build_demo_result
from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput
from app.modules.ChapterStudio_V1.app.demo_types import DemoAgentToolUse, DemoResult, DemoTimeoutPolicy
from app.modules.ChapterStudio_V1.app.study_templates import get_template, select_template_decision
from app.modules.ChapterStudio_V1.app.template_selector import TemplateDecision
from app.modules.ChapterStudio_V1.app.tutor_blueprints import blueprint_for
from app.modules.ChapterStudio_V1.common.config import codex_cli_timeout_sec

DemoEngine = Literal["mock", "codex_cli"]


class DemoAgentState(TypedDict, total=False):
    data: DemoGenerationInput
    slide_count: int
    engine: DemoEngine
    requested_template: str
    selected_template: str
    selected_label: str
    agent_plan: list[DemoAgentToolUse]
    timeout_policy: DemoTimeoutPolicy
    result: DemoResult


class CompiledDemoGraph(Protocol):
    async def ainvoke(self, state: DemoAgentState) -> DemoAgentState: ...


def demo_agent_steps(engine: str = "mock") -> list[str]:
    """수동 테스트 타임라인에 노출할 LangGraph agent 노드 이름이다."""
    generator = "Codex CLI 도구 실행" if engine == "codex_cli" else "Mock 생성 도구 실행"
    return ["Agent 입력 분석", "AI 템플릿·도구 선택", generator, "후처리·보안 렌더", "퀴즈·노트·대본 분리", "DB 저장 매핑 조립"]


async def run_demo_agent(
    data: DemoGenerationInput, slide_count: int, engine: DemoEngine, template: str
) -> DemoResult:
    """LangGraph 단일 agent가 템플릿과 생성 도구를 선택하고 결과를 조립한다."""
    graph = _compiled_graph()
    final_state = await graph.ainvoke(
        {"data": data, "slide_count": slide_count, "engine": engine, "requested_template": template}
    )
    result = final_state.get("result")
    if result is None:
        raise RuntimeError("Demo agent가 결과를 만들지 못했다.")
    return result


def build_demo_agent_graph() -> CompiledDemoGraph:
    """Phase 4 본 pipeline 전까지 데모용 단일 agent 흐름을 LangGraph로 고정한다."""
    graph = StateGraph(DemoAgentState)
    graph.add_node("agent_select", _agent_select)
    graph.add_node("agent_generate", _agent_generate)
    graph.add_node("agent_finish", _agent_finish)
    graph.set_entry_point("agent_select")
    graph.add_edge("agent_select", "agent_generate")
    graph.add_edge("agent_generate", "agent_finish")
    graph.add_edge("agent_finish", END)
    return cast(CompiledDemoGraph, graph.compile())


async def _agent_select(state: DemoAgentState) -> DemoAgentState:
    data = _data(state)
    engine = _engine(state)
    requested = state.get("requested_template", "auto")
    decision = select_template_decision(data.topic) if requested == "auto" else None
    selected = get_template(decision.key if decision is not None else requested)
    blueprint = blueprint_for(selected.key)
    return {
        "selected_template": selected.key,
        "selected_label": selected.label,
        "timeout_policy": _timeout_policy(engine),
        "agent_plan": [
            _tool("입력 분석", "DemoGenerationInput", "프론트 입력 계약을 agent state로 정규화한다.", data.topic),
            _tool("템플릿 선택", "template_selector", "점수 기반 규칙으로 학습 패턴을 고른다.", _selection_output(selected.label, decision)),
            _tool("과외 설계 선택", "tutor_blueprint", "책 요약이 아니라 과외식 관점·철학·전이 질문을 고른다.", blueprint.lens),
        ],
    }


@cache
def _compiled_graph() -> CompiledDemoGraph:
    """그래프 compile 비용을 요청마다 반복하지 않는다."""
    return build_demo_agent_graph()


async def _agent_generate(state: DemoAgentState) -> DemoAgentState:
    data = _data(state)
    engine = _engine(state)
    limit_sec = _timeout(state)["limit_sec"]
    template = _template(state)
    try:
        result = await asyncio.wait_for(_generate(data, state["slide_count"], engine, template), timeout=limit_sec)
    except asyncio.TimeoutError as exc:
        raise RuntimeError(f"{engine} 생성이 {limit_sec}초를 초과했다. 생성 도구 응답 지연이며 서버 연결 문제와 분리해서 봐야 한다.") from exc
    plan = list(state.get("agent_plan", ()))
    plan.append(_tool("생성 도구 실행", _generator_tool(engine), "선택된 생성기로 테스트 강의 1개 산출물을 만든다.", f"{len(result['slides'])} slides"))
    plan.append(_tool("후처리·보안 렌더", "postprocess_all", "Shiki, Mermaid, KaTeX, chart, nh3, iframe sandbox를 적용한다.", "allow-scripts iframe"))
    return {"result": result, "agent_plan": plan}


async def _agent_finish(state: DemoAgentState) -> DemoAgentState:
    result = _result(state)
    plan = list(state.get("agent_plan", ()))
    plan.append(_tool("산출물 분리", "DemoResultParser", "슬라이드·퀴즈·노트·과제·음성대본·DB 매핑을 분리한다.", "5 deliverables"))
    return {"result": _with_agent_metadata(result, plan, _timeout(state)), "agent_plan": plan}


async def _generate(
    data: DemoGenerationInput, slide_count: int, engine: DemoEngine, template: str
) -> DemoResult:
    if engine == "codex_cli":
        return await build_codex_demo_result(data, template)
    return await build_demo_result(data, slide_count, template)


def _with_agent_metadata(result: DemoResult, plan: list[DemoAgentToolUse], timeout: DemoTimeoutPolicy) -> DemoResult:
    return {
        "topic": result["topic"],
        "template_label": result["template_label"],
        "quality_marks": result["quality_marks"],
        "slides": result["slides"],
        "quizzes": result["quizzes"],
        "note_blocks": result["note_blocks"],
        "assignment": result["assignment"],
        "voice_scripts": result["voice_scripts"],
        "storage_preview": result["storage_preview"],
        "agent_plan": plan,
        "timeout_policy": timeout,
    }


def _timeout_policy(engine: DemoEngine) -> DemoTimeoutPolicy:
    if engine == "codex_cli":
        return {"engine": engine, "limit_sec": codex_cli_timeout_sec(), "policy": "Codex CLI OAuth 단일 실행 제한"}
    return {"engine": engine, "limit_sec": 20, "policy": "빠른 mock 검증 제한"}


def _tool(stage: str, tool: str, reason: str, output: str) -> DemoAgentToolUse:
    return {"stage": stage, "tool": tool, "reason": reason, "output": output}


def _selection_output(label: str, decision: TemplateDecision | None) -> str:
    if decision is None:
        return label
    matched = ", ".join(decision.matched[:4]) or "fallback"
    return f"{label} · score {decision.score} · {matched}"


def _generator_tool(engine: DemoEngine) -> str:
    if engine == "codex_cli":
        return "CodexCLIConnector(Sign in with ChatGPT)"
    return "MockSlideGenerator"


def _data(state: DemoAgentState) -> DemoGenerationInput:
    data = state.get("data")
    if data is None:
        raise RuntimeError("Demo agent 입력 data가 없다.")
    return data


def _engine(state: DemoAgentState) -> DemoEngine:
    engine = state.get("engine")
    if engine not in ("mock", "codex_cli"):
        raise RuntimeError("Demo agent engine 값이 올바르지 않다.")
    return engine


def _template(state: DemoAgentState) -> str:
    template = state.get("selected_template")
    if template is None:
        raise RuntimeError("Demo agent가 템플릿을 선택하지 못했다.")
    return template


def _timeout(state: DemoAgentState) -> DemoTimeoutPolicy:
    timeout = state.get("timeout_policy")
    if timeout is None:
        raise RuntimeError("Demo agent timeout 정책이 없다.")
    return timeout


def _result(state: DemoAgentState) -> DemoResult:
    result = state.get("result")
    if result is None:
        raise RuntimeError("Demo agent 생성 결과가 없다.")
    return result
