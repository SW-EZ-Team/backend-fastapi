"""Codex CLI 텍스트 생성 커넥터.

ChatGPT OAuth 세션은 codex CLI 에 위임하고,
stdout JSONL 스트림에서 agent_message 이벤트만 추출해 반환한다.
로컬 개발 및 테스트 환경용 — Modal GPU 점검 시 폴백 후보.
"""
from __future__ import annotations

import asyncio
import json
from asyncio.subprocess import DEVNULL, PIPE
from typing import TypeAlias, cast

from ai_connectors.errors import ConnectorError
from ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from ai_connectors.text_schemas import ChapterAIRequest, ChapterAIResponse
from common.text_config import codex_cli_model, codex_cli_reasoning_effort, codex_cli_timeout_sec

# JSON 값 타입 — json.loads 반환 타입을 명시해 cast 사용을 줄임
JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


class CodexCLIConnector:
    """로컬 Codex CLI 를 서브프로세스로 실행하는 커넥터.

    codex exec --json 으로 호출하고 stdout JSONL 에서
    item.completed/agent_message 이벤트를 파싱한다.
    """

    name = "codex_cli"

    def __init__(self, command: str = "codex") -> None:
        # CLI 실행 파일명 — 경로 override 가 필요하면 DI 로 주입
        self._command = command

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """ChatGPT OAuth 세션은 CLI 에 맡기고 stdout 만 정규화한다."""
        stdout, stderr, returncode = await self._run(self._build_command(req))
        if returncode != 0:
            raise ConnectorError(_failure_message(stdout, stderr))
        text = _extract_agent_text(stdout)
        return ChapterAIResponse(
            text=text,
            model=codex_cli_model(),
            # CLI 는 토큰 수를 노출하지 않아 문자 수로 근사치 추정
            input_tokens=max(len(req.user) // 4, 0),
            output_tokens=max(len(text) // 4, 0),
            finish_reason="stop",
        )

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        """소량 검증 목적이므로 순서 보존 gather 만 사용한다."""
        return list(await asyncio.gather(*[self.generate(r) for r in reqs]))

    def supports(self, feature: str) -> bool:
        return feature in {"codex_oauth", "local_dev", "output_schema"}

    def _build_command(self, req: ChapterAIRequest) -> list[str]:
        """codex exec 커맨드 인수 목록을 구성한다."""
        cmd = [
            self._command,
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "-c",
            f'model_reasoning_effort="{codex_cli_reasoning_effort()}"',
            "-m",
            codex_cli_model(),
        ]
        # output_schema_path 가 extra 에 있으면 JSON 스키마 강제 적용
        schema_path = req.extra.get("output_schema_path")
        if isinstance(schema_path, str) and schema_path:
            cmd.extend(["--output-schema", schema_path])
        cmd.append(_compose_prompt(req))
        return cmd

    async def _run(self, command: list[str]) -> tuple[str, str, int]:
        """서브프로세스를 실행하고 (stdout, stderr, returncode) 를 반환한다."""
        try:
            # create_subprocess_exec 사용 — 쉘 injection 방지 (exec 미사용)
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=DEVNULL,
                stdout=PIPE,
                stderr=PIPE,
            )
        except OSError as exc:
            raise ConnectorError(f"codex_cli 실행 실패: {exc}") from exc
        return await _communicate(process, codex_cli_timeout_sec())


# --- 순수 함수 헬퍼 ---

async def _communicate(
    process: asyncio.subprocess.Process, timeout_sec: int
) -> tuple[str, str, int]:
    """타임아웃 내에 프로세스 통신을 완료하고 결과를 반환한다."""
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=timeout_sec
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ConnectorTimeoutError(f"codex_cli {timeout_sec}초 초과") from exc
    return (
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
        process.returncode or 0,
    )


def _compose_prompt(req: ChapterAIRequest) -> str:
    """system + user 를 하나의 문자열로 합친다."""
    system = req.system.strip()
    if not system:
        return req.user
    return f"{system}\n\n사용자 요청:\n{req.user}"


def _extract_agent_text(stdout: str) -> str:
    """stdout JSONL 에서 마지막 agent_message 텍스트를 추출한다."""
    last_text: str | None = None
    for line in stdout.splitlines():
        event = _parse_event(line)
        if event is None:
            continue
        last_text = _agent_text(event) or last_text
        _raise_failed_event(event)
    if last_text is None:
        raise ConnectorError("codex_cli 응답에서 agent_message를 찾지 못했다.")
    return last_text


def _parse_event(line: str) -> dict[str, JsonValue] | None:
    """한 줄을 JSON dict 로 파싱한다. 실패하면 None 을 반환한다."""
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    value = cast(JsonValue, json.loads(stripped))
    if not isinstance(value, dict):
        return None
    return value


def _agent_text(event: dict[str, JsonValue]) -> str | None:
    """item.completed + agent_message 이벤트에서 text 를 추출한다."""
    item = event.get("item")
    if event.get("type") != "item.completed" or not isinstance(item, dict):
        return None
    if item.get("type") != "agent_message":
        return None
    text = item.get("text")
    return text if isinstance(text, str) else None


def _raise_failed_event(event: dict[str, JsonValue]) -> None:
    """error 또는 turn.failed 이벤트를 ConnectorError 로 변환한다."""
    if event.get("type") not in {"error", "turn.failed"}:
        return
    message = event.get("message")
    if isinstance(message, str):
        raise ConnectorError(message)
    raise ConnectorError("codex_cli turn 실패")


def _failure_message(stdout: str, stderr: str) -> str:
    """비정상 종료 상세 메시지를 구성한다."""
    detail = stderr.strip() or stdout.strip() or "원인 없음"
    return f"codex_cli 비정상 종료: {detail[-800:]}"
