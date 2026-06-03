"""A항: ChapterStudio CodexCLI connector transient retry 통합 테스트.

LLM 실호출 없이 mock subprocess로 커넥터가 공용 retry 모듈을 통해 재시도하는지 검증한다:
    - transient 오류(rc=1 + 503 키워드) → 재시도 후 성공
    - 영구 오류(rc=1 + 키워드 없음) → 즉시 ConnectorError
    - 재시도 한도 초과(transient 계속) → ConnectorError
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.codex_cli_connector import (
    CodexCLIConnector,
    _is_transient,
)
from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest


# ── 헬퍼 ─────────────────────────────────────────────────────────────────

def _req() -> ChapterAIRequest:
    return ChapterAIRequest(user="테스트 요청", max_tokens=100, temperature=0.1)


def _success_stdout() -> str:
    """정상 응답 JSONL 문자열."""
    return '{"type":"item.completed","item":{"type":"agent_message","text":"정상 응답"}}\n'


def _transient_stderr() -> str:
    """transient 오류 stderr — 503 키워드 포함."""
    return "WebSocket 503 Service Unavailable"


def _permanent_stderr() -> str:
    """영구 오류 stderr — 인증 실패 키워드."""
    return "authentication failed: invalid oauth token"


# ── 커넥터가 공용 _is_transient 별칭을 노출하는지 ────────────────────────

def test_connector_reexports_is_transient() -> None:
    """하위호환: 커넥터 모듈의 _is_transient 별칭이 공용 판정 함수와 동일하게 작동한다."""
    assert _is_transient("error: 503 service unavailable") is True
    assert _is_transient("authentication failed") is False


# ── connector.generate retry 동작 (공용 retry 모듈 위임) ─────────────────

@pytest.mark.asyncio
async def test_transient_then_success_retries() -> None:
    """transient 오류 1회 후 성공 → 재시도해 정상 응답을 반환한다."""
    connector = CodexCLIConnector(command="codex-mock")

    # 1차 호출: transient(rc=1, 503 stderr), 2차 호출: 성공(rc=0)
    call_results = [
        ("", _transient_stderr(), 1),
        (_success_stdout(), "", 0),
    ]
    call_iter = iter(call_results)

    async def mock_run(cmd: list[str]) -> tuple[str, str, int]:
        return next(call_iter)

    # sleep은 공용 retry 모듈에서 호출되므로 그쪽을 패치한다.
    with (
        patch.object(connector, "_run", side_effect=mock_run),
        patch(
            "ai_connectors.common.codex_retry.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        resp = await connector.generate(_req())

    assert resp.text == "정상 응답"


@pytest.mark.asyncio
async def test_permanent_error_raises_immediately() -> None:
    """영구 오류(rc=1, 키워드 없음) → 즉시 ConnectorError, 재시도 없음."""
    connector = CodexCLIConnector(command="codex-mock")
    call_count = 0

    async def mock_run(cmd: list[str]) -> tuple[str, str, int]:
        nonlocal call_count
        call_count += 1
        return ("", _permanent_stderr(), 1)

    with patch.object(connector, "_run", side_effect=mock_run):
        with pytest.raises(ConnectorError):
            await connector.generate(_req())

    # 영구 오류는 1회만 시도해야 한다
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_limit_exhaustion_raises() -> None:
    """transient 오류가 한도까지 계속되면 ConnectorError를 던진다."""
    connector = CodexCLIConnector(command="codex-mock")

    async def mock_run(cmd: list[str]) -> tuple[str, str, int]:
        return ("", _transient_stderr(), 1)

    with (
        patch.object(connector, "_run", side_effect=mock_run),
        patch(
            "ai_connectors.common.codex_retry.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        with pytest.raises(ConnectorError, match="한도 초과"):
            await connector.generate(_req())
