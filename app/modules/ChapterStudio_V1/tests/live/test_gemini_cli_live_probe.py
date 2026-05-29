from __future__ import annotations

import os

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.gemini_cli_live_probe import run_gemini_cli_live_probe

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI_CLI") != "1",
    reason="RUN_LIVE_GEMINI_CLI=1일 때만 Gemini CLI 실제 호출을 실행한다.",
)


@pytest.mark.asyncio
async def test_gemini_cli_live_probe_calls_real_cli() -> None:
    result = await run_gemini_cli_live_probe(
        "Rust 언어 강의 생성 테스트다. ok=true 의미를 가진 JSON 객체로만 짧게 응답해줘."
    )

    assert result["ok"] is True
    assert result["connector"] == "gemini_cli"
    assert result["secret_value_printed"] is False
    assert result["response_json_valid"] is True
    assert isinstance(result["response_text"], str)
    assert len(result["response_text"].strip()) > 0
