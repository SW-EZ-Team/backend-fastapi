"""Codex CLI(GPT-5.4) 기반 커넥터. ChatGPT OAuth 인증은 CLI에 위임한다."""
# asyncio.create_subprocess_exec은 args 리스트를 받아 쉘 경유 없이 직접 실행하므로
# 쉘 인젝션 위험이 없다 (shell=False 동등).
from __future__ import annotations

import asyncio
import json
import shutil
from asyncio.subprocess import DEVNULL

from ai_connectors.common.codex_retry import run_codex_with_retry
from app.modules.ExamForge_V1.common._ai_schemas import (
    ChapterAIRequest,
    ChapterAIResponse,
    LLMBudgetCounter,
    current_budget,
)
from app.modules.ExamForge_V1.common.config import codex_cli_model, codex_cli_timeout_sec


class CodexCliConnector:
    """Codex CLI를 통해 GPT-5.4와 통신하는 커넥터.

    transient 오류(rc!=0 + 503/429/연결 키워드)는 공용 retry 모듈로 지수 백오프
    재시도하며, 영구 오류(인증 실패·잘못된 인자 등)는 즉시 실패한다.
    """

    def __init__(self) -> None:
        # codex 바이너리 존재 여부를 초기화 시점에 확인한다
        if shutil.which("codex") is None:
            raise RuntimeError("codex CLI가 설치되지 않았다.")
        self.name = "codex_cli"

    async def generate(
        self,
        req: ChapterAIRequest,
        budget: LLMBudgetCounter | None = None,
    ) -> ChapterAIResponse:
        """Codex CLI를 --json 모드로 실행하고 agent_message 텍스트를 추출한다.

        transient 오류 시 공용 retry 헬퍼가 지수 백오프 재시도를 수행한다.
        예산 증가는 최종 성공 시 1회만 반영한다(재시도가 예산을 중복 소모하지 않음).
        """
        # 예산 체크는 allow_reserve 인자를 생략해 카운터가 contextvar에서
        # 해설 생성 구간 여부를 자동 반영하게 한다(핵심 산출물 보호).
        if budget is None:
            budget = current_budget.get()
        if budget is not None:
            budget.check()

        cmd = _build_command(req)
        # stderr에 "Reading additional input from stdin..." 같은 알림 메시지가
        # 오는 경우가 있으므로 returncode 0이면 stderr는 무시한다.
        stdout, _stderr = await run_codex_with_retry(
            lambda: _run(cmd),
            on_permanent=lambda out, err: RuntimeError(_failure_message(out, err)),
            on_exhausted=lambda out, err, rc: RuntimeError(
                "codex CLI transient 오류 재시도 한도 초과 — 포기: "
                + _failure_message(out, err)
            ),
            connector_label="codex_cli(ExamForge)",
        )

        text = _extract_agent_text(stdout)
        if budget is not None:
            budget.increment()
        return ChapterAIResponse(
            text=text,
            model=codex_cli_model(),
            # 토큰 수는 CLI가 노출하지 않으므로 글자 수 기반 추정값을 사용한다
            input_tokens=max(len(req.user) // 4, 0),
            output_tokens=max(len(text) // 4, 0),
            finish_reason="stop",
        )

    def supports(self, feature: str) -> bool:
        """지원 기능 확인."""
        return feature in {"codex_oauth", "local_dev", "json_mode"}


def _build_command(req: ChapterAIRequest) -> list[str]:
    """Codex CLI 실행 명령을 구성한다.

    extra.output_schema_path 가 지정되면 --output-schema 를 추가해
    codex 가 해당 JSON Schema 규격으로 응답을 강제하도록 한다.
    이를 통해 정답/해설 필드가 누락되거나 형식이 깨지는 파싱 실패를 차단한다.
    """
    prompt = _compose_prompt(req)
    cmd = [
        "codex", "exec",
        "--json",
        "--sandbox", "read-only",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-m", codex_cli_model(),
    ]
    schema_path = req.extra.get("output_schema_path")
    if isinstance(schema_path, str) and schema_path:
        cmd.extend(["--output-schema", schema_path])
    cmd.append(prompt)
    return cmd


async def _run(command: list[str]) -> tuple[str, str, int]:
    """서브프로세스를 실행하고 stdout/stderr/returncode를 반환한다."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise RuntimeError(f"codex CLI 실행 실패: {exc}") from exc

    timeout = float(codex_cli_timeout_sec())
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"codex CLI 호출 시간 초과: {timeout:.0f}초") from exc
    return (
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
        proc.returncode or 0,
    )


def _failure_message(stdout: str, stderr: str) -> str:
    """비정상 종료 상세 메시지를 구성한다(retry on_permanent/on_exhausted 공용)."""
    detail = (stderr.strip() or stdout.strip() or "원인 없음")[-800:]
    return f"codex CLI 비정상 종료: {detail}"


def _compose_prompt(req: ChapterAIRequest) -> str:
    """시스템/사용자 지시를 하나의 프롬프트 문자열로 합친다."""
    system = req.system.strip()
    if not system:
        return req.user
    return f"{system}\n\n사용자 요청:\n{req.user}"


def _extract_agent_text(stdout: str) -> str:
    """NDJSON 스트림에서 마지막 item.completed agent_message 텍스트를 추출한다."""
    last_text: str | None = None
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event: dict = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        # 오류 이벤트 감지 후 즉시 예외 발생
        if event.get("type") in {"error", "turn.failed"}:
            msg = event.get("message")
            raise RuntimeError(
                msg if isinstance(msg, str) else "codex CLI turn 실패"
            )
        # item.completed 이벤트에서 agent_message 텍스트 추출
        if event.get("type") == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    last_text = text
    if last_text is None:
        raise RuntimeError("codex CLI 응답에서 agent_message를 찾지 못했다.")
    return last_text
