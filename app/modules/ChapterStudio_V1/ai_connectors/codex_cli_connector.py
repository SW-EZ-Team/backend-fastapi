from __future__ import annotations

import asyncio
import json
from asyncio.subprocess import DEVNULL, PIPE
from typing import TypeAlias, cast

from ai_connectors.common.codex_retry import is_transient_error, run_codex_with_retry
from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError, TimeoutError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.common.config import codex_cli_model, codex_cli_reasoning_effort, codex_cli_timeout_sec

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

# transient 판정은 공용 모듈에 위임한다(키워드 단일 소스 유지).
# 하위호환을 위해 모듈 레벨 _is_transient 별칭을 유지한다(기존 테스트·import 보호).
_is_transient = is_transient_error


class CodexCLIConnector:
    """로컬 Codex CLI 를 서브프로세스로 실행하는 커넥터.

    transient 오류(rc=1 + 503/429/연결 키워드)는 지수 백오프 재시도하며,
    영구 오류(인증 실패·잘못된 인자 등)는 즉시 실패한다(공용 retry 모듈 사용).
    """

    name = "codex_cli"

    def __init__(self, command: str = "codex") -> None:
        self._command = command

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """ChatGPT OAuth 세션은 CLI에 맡기고 stdout만 정규화한다.

        transient 오류 시 공용 retry 헬퍼가 지수 백오프 재시도를 수행한다.
        영구 오류·한도 초과는 ConnectorError로 올린다.
        """
        cmd = self._build_command(req)
        stdout, _stderr = await run_codex_with_retry(
            lambda: self._run(cmd),
            on_permanent=lambda out, err: ConnectorError(_failure_message(out, err)),
            on_exhausted=lambda out, err, rc: ConnectorError(
                "codex_cli transient 오류 재시도 한도 초과 — 포기: "
                + _failure_message(out, err)
            ),
            connector_label="codex_cli",
        )
        text = _extract_agent_text(stdout)
        return ChapterAIResponse(
            text=text,
            model=codex_cli_model(),
            input_tokens=max(len(req.user) // 4, 0),
            output_tokens=max(len(text) // 4, 0),
            finish_reason="stop",
        )

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        """수동 테스트는 소량 검증이므로 순서 보존 gather만 사용한다."""
        return await asyncio.gather(*[self.generate(req) for req in reqs])

    def supports(self, feature: str) -> bool:
        # "batch" 포함: 12슬라이드+퀴즈+voice_scripts를 단일 거대 콜로 요청하면
        # 180초 타임아웃을 초과하므로(P0), 컴포넌트별 병렬 경로를 쓴다.
        # 각 컴포넌트 콜은 작아 180초 내에 충분히 완료된다.
        return feature in {"batch", "codex_oauth", "local_dev", "output_schema", "voice_quality_repair"}

    def _build_command(self, req: ChapterAIRequest) -> list[str]:
        command = [
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
        schema_path = req.extra.get("output_schema_path")
        if isinstance(schema_path, str) and schema_path:
            command.extend(["--output-schema", schema_path])
        command.append(_compose_prompt(req))
        return command

    async def _run(self, command: list[str]) -> tuple[str, str, int]:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=DEVNULL,
                stdout=PIPE,
                stderr=PIPE,
            )
            # stdin=DEVNULL: CLI가 대화형 입력을 기다리지 않도록 막아 hang을 방지한다
        except OSError as exc:
            raise ConnectorError(f"codex_cli 실행 실패: {exc}") from exc
        return await _communicate(process, codex_cli_timeout_sec())


async def _communicate(process: asyncio.subprocess.Process, timeout_sec: int) -> tuple[str, str, int]:
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise TimeoutError(f"codex_cli {timeout_sec}초 초과") from exc
    return (
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
        process.returncode or 0,
    )


def _compose_prompt(req: ChapterAIRequest) -> str:
    system = req.system.strip()
    if not system:
        return req.user
    return f"{system}\n\n사용자 요청:\n{req.user}"


def _extract_agent_text(stdout: str) -> str:
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
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    value = cast(JsonValue, json.loads(stripped))
    if not isinstance(value, dict):
        return None
    return value


def _agent_text(event: dict[str, JsonValue]) -> str | None:
    item = event.get("item")
    if event.get("type") != "item.completed" or not isinstance(item, dict):
        return None
    if item.get("type") != "agent_message":
        return None
    text = item.get("text")
    return text if isinstance(text, str) else None


def _raise_failed_event(event: dict[str, JsonValue]) -> None:
    if event.get("type") not in {"error", "turn.failed"}:
        return
    message = event.get("message")
    if isinstance(message, str):
        raise ConnectorError(message)
    raise ConnectorError("codex_cli turn 실패")


def _failure_message(stdout: str, stderr: str) -> str:
    detail = stderr.strip() or stdout.strip() or "원인 없음"
    return f"codex_cli 비정상 종료: {detail[-800:]}"
