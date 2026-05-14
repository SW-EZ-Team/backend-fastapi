from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.app.demo_agent import demo_agent_steps, run_demo_agent
from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput


def test_demo_agent_steps_explain_tools() -> None:
    steps = demo_agent_steps("codex_cli")
    assert steps[0] == "Agent 입력 분석"
    assert "Codex CLI 도구 실행" in steps


@pytest.mark.asyncio
async def test_demo_agent_adds_tool_plan_and_timeout() -> None:
    result = await run_demo_agent(_input("통계학자 로널드 피셔"), 5, "mock", "auto")
    assert result["template_label"] == "인물 탐구"
    assert result["timeout_policy"]["engine"] == "mock"
    assert len(result["agent_plan"]) >= 5
    assert any(item["tool"] == "template_selector" for item in result["agent_plan"])
    assert any(item["tool"] == "tutor_blueprint" for item in result["agent_plan"])
    assert any(item["tool"] == "postprocess_all" for item in result["agent_plan"])
    assert "score" in result["agent_plan"][1]["output"]


@pytest.mark.asyncio
async def test_demo_agent_note_avoids_overview_label() -> None:
    result = await run_demo_agent(_input("낯선 자유주제"), 5, "mock", "auto")
    headings = [block["heading"] for block in result["note_blocks"]]
    assert "기본 철학" in headings
    assert all("개요" not in heading for heading in headings)


def _input(topic: str) -> DemoGenerationInput:
    return DemoGenerationInput(topic=topic, duration_days=30, audience_level="초중급 학습자")
