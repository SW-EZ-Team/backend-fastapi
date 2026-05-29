"""Gemini CLI 테스트 전용 패스스루 모듈 검증."""
from __future__ import annotations

import os

import pytest

from app.modules.ExamForge_V1.test_runtime import gemini_cli_passthrough
from app.modules.ExamForge_V1.test_runtime.gemini_cli_passthrough import (
    CliResult,
    GeminiCliPassthrough,
    _cli_env,
    extract_response_text,
)


class _FakeRunner:
    """실제 Gemini CLI를 호출하지 않는 테스트 실행기."""

    command: list[str] | None = None

    async def run(self, command: list[str], timeout_sec: int) -> CliResult:
        """명령을 기록하고 고정 JSON stdout을 반환한다."""
        self.command = command
        return CliResult(
            stdout='{"response":"{\\"questions\\": []}","stats":{"models":{}}}',
            stderr="",
            returncode=0,
        )


def test_extract_response_text_preserves_response_field() -> None:
    """JSON 래퍼의 response 문자열을 보정하지 않고 반환한다."""
    raw = '{"response":"  그대로\\n응답  "}'

    assert extract_response_text(raw) == "  그대로\n응답  "


async def test_capture_requires_explicit_test_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """명시 플래그 없이는 테스트 커넥터도 실행되지 않는다."""
    monkeypatch.delenv("EXAMFORGE_GEMINI_CLI_TEST_ENABLED", raising=False)

    connector = GeminiCliPassthrough(runner=_FakeRunner())

    with pytest.raises(RuntimeError, match="TEST_ENABLED"):
        await connector.capture("prompt")


async def test_capture_uses_plan_mode_and_redacts_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini CLI는 plan 모드로 실행하고 보고용 명령에서는 프롬프트를 가린다."""
    monkeypatch.setenv("EXAMFORGE_GEMINI_CLI_TEST_ENABLED", "true")
    fake = _FakeRunner()

    connector = GeminiCliPassthrough(model="gemini-test", runner=fake)
    capture = await connector.capture("민감한 프롬프트", timeout_sec=30)

    assert fake.command is not None
    assert "--approval-mode" in fake.command
    assert "plan" in fake.command
    assert "--output-format" in fake.command
    assert "json" in fake.command
    assert capture.command[-1] == "<prompt>"
    assert capture.raw_response == '{"questions": []}'


def test_no_secret_env_is_required() -> None:
    """테스트 커넥터는 별도 API 키 환경변수를 요구하지 않는다."""
    assert "EXAMFORGE_GEMINI_API_KEY" not in os.environ


async def test_fake_runner_does_not_require_installed_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """가짜 runner 단위 테스트는 로컬 gemini 설치 상태와 분리된다."""
    monkeypatch.setenv("EXAMFORGE_GEMINI_CLI_TEST_ENABLED", "true")
    monkeypatch.setattr(gemini_cli_passthrough.shutil, "which", lambda _: None)
    fake = _FakeRunner()

    connector = GeminiCliPassthrough(model="gemini-test", runner=fake)
    capture = await connector.capture("prompt", timeout_sec=30)

    assert fake.command is not None
    assert fake.command[:2] == ["node", "gemini"]
    assert capture.raw_response == '{"questions": []}'


def test_cli_env_prefers_gemini_bin_node(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨진 전역 node보다 Gemini CLI와 같은 bin의 node를 우선한다."""
    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/bin")

    env = _cli_env(["/Users/me/.nvm/versions/node/v24/bin/gemini"])

    assert env["PATH"].startswith("/Users/me/.nvm/versions/node/v24/bin:")
