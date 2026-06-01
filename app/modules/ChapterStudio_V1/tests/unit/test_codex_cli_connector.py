from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.codex_cli_connector import CodexCLIConnector, _extract_agent_text
from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest


def test_codex_cli_extracts_last_agent_message() -> None:
    stdout = (
        '{"type":"thread.started","thread_id":"t"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"첫 응답"}}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"최종 응답"}}\n'
    )
    assert _extract_agent_text(stdout) == "최종 응답"


def test_codex_cli_raises_on_failed_turn() -> None:
    stdout = '{"type":"turn.failed","error":{"message":"실패"}}\n'
    with pytest.raises(ConnectorError):
        _extract_agent_text(stdout)


def test_codex_cli_command_uses_schema_and_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODEX_CLI_REASONING_EFFORT", raising=False)
    req = ChapterAIRequest(
        user="테스트",
        max_tokens=100,
        temperature=0.1,
        extra={"output_schema_path": "/tmp/schema.json"},
    )
    command = CodexCLIConnector(command="codex-test")._build_command(req)
    assert command[:5] == ["codex-test", "exec", "--json", "--sandbox", "read-only"]
    assert "--ephemeral" in command
    assert 'model_reasoning_effort="low"' in command
    assert "--output-schema" in command
    assert "/tmp/schema.json" in command
