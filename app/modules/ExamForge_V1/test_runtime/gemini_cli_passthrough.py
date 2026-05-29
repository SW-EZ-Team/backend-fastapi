"""Gemini CLI 테스트 전용 패스스루 커넥터."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import uuid
from asyncio.subprocess import DEVNULL, PIPE
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CliResult:
    """CLI 프로세스 실행 결과."""

    stdout: str
    stderr: str
    returncode: int


@dataclass(frozen=True)
class GeminiCliCapture:
    """Gemini CLI 원본 응답 보존 결과."""

    command: list[str]
    model: str
    prompt: str
    stdout: str
    stderr: str
    returncode: int
    raw_response: str
    started_at: str
    duration_sec: float

    def to_dict(self) -> dict[str, object]:
        """JSON 저장용 딕셔너리로 변환한다."""
        return asdict(self)


class AsyncCliRunner(Protocol):
    """테스트에서 CLI 실행을 대체하기 위한 프로토콜."""

    async def run(self, command: list[str], timeout_sec: int) -> CliResult:
        """명령을 실행하고 stdout/stderr/returncode를 반환한다."""


class SubprocessCliRunner:
    """실제 Gemini CLI 서브프로세스 실행기."""

    async def run(self, command: list[str], timeout_sec: int) -> CliResult:
        """임시 디렉터리에서 CLI를 실행해 워크스페이스 접근을 피한다."""
        env = _cli_env(command)
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=DEVNULL,
            stdout=PIPE,
            stderr=PIPE,
            cwd=tempfile.gettempdir(),
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_sec
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise TimeoutError(f"Gemini CLI {timeout_sec}초 초과") from None
        return CliResult(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            returncode=process.returncode or 0,
        )


class GeminiCliPassthrough:
    """Gemini CLI 응답을 수정하지 않고 캡처한다."""

    def __init__(
        self,
        model: str | None = None,
        runner: AsyncCliRunner | None = None,
        command: str | None = None,
        node_command: str | None = None,
    ) -> None:
        resolved_command = command or shutil.which("gemini")
        if resolved_command is None and runner is None:
            raise RuntimeError("gemini CLI가 설치되지 않았다.")
        self._command = resolved_command or "gemini"
        self._node_command = node_command or (
            "node" if self._command == "gemini" else _node_for(self._command)
        )
        self._model = model or os.getenv(
            "EXAMFORGE_GEMINI_CLI_MODEL", "gemini-2.5-flash"
        )
        self._runner = runner or SubprocessCliRunner()

    async def capture(self, prompt: str, timeout_sec: int | None = None) -> GeminiCliCapture:
        """테스트 플래그가 켜진 경우에만 Gemini CLI를 호출한다."""
        if not _enabled():
            raise RuntimeError(
                "EXAMFORGE_GEMINI_CLI_TEST_ENABLED=true 일 때만 실행할 수 있다."
            )
        started = _utc_stamp()
        start_time = time.perf_counter()
        command = self._build_command(prompt)
        result = await self._runner.run(command, timeout_sec or _timeout_sec())
        return GeminiCliCapture(
            command=_redacted_command(command),
            model=self._model,
            prompt=prompt,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            raw_response=extract_response_text(result.stdout),
            started_at=started,
            duration_sec=round(time.perf_counter() - start_time, 3),
        )

    def _build_command(self, prompt: str) -> list[str]:
        """도구 실행을 막는 plan 모드 명령을 만든다."""
        return [
            self._node_command,
            self._command,
            "--skip-trust",
            "--approval-mode",
            "plan",
            "--session-id",
            str(uuid.uuid4()),
            "--output-format",
            "json",
            "--model",
            self._model,
            "-p",
            prompt,
        ]


def extract_response_text(stdout: str) -> str:
    """Gemini CLI JSON 래퍼에서 response 필드만 원문 그대로 꺼낸다."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout
    if not isinstance(payload, dict):
        return stdout
    response = payload.get("response")
    return response if isinstance(response, str) else stdout


def _enabled() -> bool:
    """테스트 전용 실행 플래그를 확인한다."""
    return os.getenv("EXAMFORGE_GEMINI_CLI_TEST_ENABLED", "").lower() == "true"


def _timeout_sec() -> int:
    """Gemini CLI 호출 제한 시간을 반환한다."""
    raw = os.getenv("EXAMFORGE_GEMINI_CLI_TIMEOUT_SEC", "240")
    try:
        return max(30, min(int(raw), 600))
    except ValueError:
        return 240


def _utc_stamp() -> str:
    """파일명과 보고서에 쓸 UTC 타임스탬프를 만든다."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _redacted_command(command: list[str]) -> list[str]:
    """긴 프롬프트는 보고서 명령 표시에서 축약한다."""
    cleaned = command.copy()
    if "-p" in cleaned:
        index = cleaned.index("-p")
        if index + 1 < len(cleaned):
            cleaned[index + 1] = "<prompt>"
    return cleaned


def _cli_env(command: list[str]) -> dict[str, str]:
    """Gemini CLI와 같은 nvm bin의 node가 먼저 잡히도록 PATH를 보정한다."""
    env = {**os.environ, "TERM": "xterm-256color"}
    if command:
        anchor = command[1] if len(command) > 1 and command[1].endswith("gemini") else command[0]
        bin_dir = str(Path(anchor).parent)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return env


def _node_for(gemini_command: str) -> str:
    """Gemini CLI와 같은 nvm bin의 node를 우선 사용한다."""
    sibling = Path(gemini_command).with_name("node")
    if sibling.exists():
        return str(sibling)
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node 실행 파일을 찾지 못했다.")
    return node
