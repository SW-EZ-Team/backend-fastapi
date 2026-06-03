"""P0: ExamForge codex 커넥터 transient retry 단위 테스트.

ExamForge get_text_connector/get_verifier_connector가 codex_cli로 라우팅될 때,
무패치 커넥터가 503/429에 즉시 실패하던 결함을 회귀 방지한다.
LLM 실호출 없이 mock subprocess로 검증한다:
    - transient(503/429) → 재시도 후 성공
    - 영구 오류 → 즉시 실패(재시도 없음)
    - 한도 초과 → 예외
    - 예산은 최종 성공 시 1회만 증가(재시도가 예산 중복 소모 안 함)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.modules.ExamForge_V1.common._ai_schemas import (
    ChapterAIRequest,
    LLMBudgetCounter,
)


def _make_connector():
    """codex 바이너리 존재 확인을 우회해 커넥터를 생성한다."""
    with patch(
        "app.modules.ExamForge_V1.common._connector_codex.shutil.which",
        return_value="/usr/bin/codex",
    ):
        from app.modules.ExamForge_V1.common._connector_codex import CodexCliConnector

        return CodexCliConnector()


def _req() -> ChapterAIRequest:
    return ChapterAIRequest(user="테스트 요청", max_tokens=100, temperature=0.1)


def _success_stdout() -> str:
    return '{"type":"item.completed","item":{"type":"agent_message","text":"정상 응답"}}\n'


@pytest.mark.asyncio
async def test_examforge_codex_transient_then_success() -> None:
    """503 transient 1회 후 성공 → 재시도해 정상 응답을 반환한다."""
    connector = _make_connector()
    results = iter([("", "503 Service Unavailable websocket", 1), (_success_stdout(), "", 0)])

    async def mock_run(cmd: list[str]) -> tuple[str, str, int]:
        return next(results)

    with (
        patch("app.modules.ExamForge_V1.common._connector_codex._run", side_effect=mock_run),
        patch("ai_connectors.common.codex_retry.asyncio.sleep", new=AsyncMock()),
    ):
        resp = await connector.generate(_req())

    assert resp.text == "정상 응답"


@pytest.mark.asyncio
async def test_examforge_codex_429_transient_retries() -> None:
    """P1 회귀: 429 too many requests도 transient로 재시도한다."""
    connector = _make_connector()
    results = iter([("", "429 too many requests", 1), (_success_stdout(), "", 0)])

    async def mock_run(cmd: list[str]) -> tuple[str, str, int]:
        return next(results)

    with (
        patch("app.modules.ExamForge_V1.common._connector_codex._run", side_effect=mock_run),
        patch("ai_connectors.common.codex_retry.asyncio.sleep", new=AsyncMock()),
    ):
        resp = await connector.generate(_req())

    assert resp.text == "정상 응답"


@pytest.mark.asyncio
async def test_examforge_codex_permanent_error_no_retry() -> None:
    """영구 오류(인증 실패) → 즉시 RuntimeError, 재시도 없음."""
    connector = _make_connector()
    call_count = 0

    async def mock_run(cmd: list[str]) -> tuple[str, str, int]:
        nonlocal call_count
        call_count += 1
        return ("", "authentication failed: invalid oauth token", 1)

    with patch(
        "app.modules.ExamForge_V1.common._connector_codex._run", side_effect=mock_run
    ):
        with pytest.raises(RuntimeError):
            await connector.generate(_req())

    assert call_count == 1


@pytest.mark.asyncio
async def test_examforge_codex_exhaustion_raises() -> None:
    """transient가 한도까지 계속되면 RuntimeError를 던진다."""
    connector = _make_connector()

    async def mock_run(cmd: list[str]) -> tuple[str, str, int]:
        return ("", "503 service unavailable", 1)

    with (
        patch("app.modules.ExamForge_V1.common._connector_codex._run", side_effect=mock_run),
        patch("ai_connectors.common.codex_retry.asyncio.sleep", new=AsyncMock()),
    ):
        with pytest.raises(RuntimeError, match="한도 초과"):
            await connector.generate(_req())


@pytest.mark.asyncio
async def test_examforge_codex_budget_increments_once_after_retries() -> None:
    """재시도가 있어도 예산은 최종 성공 시 1회만 증가한다(중복 소모 방지)."""
    connector = _make_connector()
    budget = LLMBudgetCounter(budget=5)
    results = iter([("", "503 service unavailable", 1), (_success_stdout(), "", 0)])

    async def mock_run(cmd: list[str]) -> tuple[str, str, int]:
        return next(results)

    with (
        patch("app.modules.ExamForge_V1.common._connector_codex._run", side_effect=mock_run),
        patch("ai_connectors.common.codex_retry.asyncio.sleep", new=AsyncMock()),
    ):
        await connector.generate(_req(), budget=budget)

    # 재시도 1회 발생했지만 예산 카운트는 1이어야 한다
    assert budget.count == 1
