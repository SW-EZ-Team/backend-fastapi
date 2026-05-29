"""Gemini CLI 기반 커넥터."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid

from app.modules.ExamForge_V1.common._ai_schemas import (
    ChapterAIRequest,
    ChapterAIResponse,
    LLMBudgetCounter,
    current_budget,
)

# Gemini CLI 동시 호출 직렬화 락 (race condition 방지)
_GEMINI_CLI_LOCK = asyncio.Lock()


class GeminiCliConnector:
    """Gemini CLI를 headless 모드로 호출하는 커넥터."""

    def __init__(self, model_id: str, connector_name: str) -> None:
        if shutil.which("gemini") is None:
            raise RuntimeError("gemini CLI가 설치되지 않았다.")
        self._model = model_id
        self.name = connector_name

    async def generate(
        self,
        req: ChapterAIRequest,
        budget: LLMBudgetCounter | None = None,
    ) -> ChapterAIResponse:
        """Gemini CLI를 headless 모드로 호출한다."""
        if budget is None:
            budget = current_budget.get()
        if budget is not None:
            budget.check()

        prompt = _build_prompt(req)
        stdout = await self._call_cli(prompt)
        text = _clean_output(stdout)
        if not text:
            raise ValueError("Gemini CLI 빈 응답")
        if budget is not None:
            budget.increment()
        return ChapterAIResponse(
            text=text,
            model=self._model,
            input_tokens=0,
            output_tokens=0,
            finish_reason="cli_complete",
        )

    def supports(self, feature: str) -> bool:
        """지원 기능 확인."""
        return feature in {"long_context", "json_mode", "cli"}

    async def _call_cli(self, prompt: str) -> str:
        """도구 없는 새 세션으로 Gemini CLI를 실행한다."""
        env = {**os.environ, "TERM": "xterm-256color"}
        async with _GEMINI_CLI_LOCK:
            # asyncio.create_subprocess_exec은 인수를 리스트로 받아 쉘 인젝션 위험이 없다
            proc = await asyncio.create_subprocess_exec(
                "gemini",
                "--skip-trust",
                "--session-id", str(uuid.uuid4()),
                "-m", self._model,
                "-p", prompt,
                "--output-format", "json",
                cwd=tempfile.gettempdir(),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            timeout_sec = float(os.environ.get("GEMINI_CLI_TIMEOUT_SEC", "240"))
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_sec
                )
            except asyncio.TimeoutError as exc:
                proc.kill()
                await proc.wait()
                raise TimeoutError(
                    f"Gemini CLI 호출 시간 초과: {timeout_sec:.0f}초"
                ) from exc
            output = stdout.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Gemini CLI 실패({proc.returncode}): {output[:800]}"
                )
            return output


def _build_prompt(req: ChapterAIRequest) -> str:
    """CLI 단일 프롬프트로 시스템/사용자 지시를 합친다."""
    return (
        "도구를 사용하지 말고, 파일을 읽거나 수정하지 말고, "
        "아래 요청에 대한 최종 답변만 생성하시오.\n\n"
        f"[시스템]\n{req.system}\n\n"
        f"[사용자]\n{req.user}"
    )


def _clean_output(output: str) -> str:
    """CLI 경고 줄을 제거하고 JSON 래퍼의 모델 본문만 남긴다."""
    blocked_prefixes = (
        "Warning:", "Ripgrep is not available.",
        "(node:", "[LocalAgentExecutor]", "Error executing tool",
    )
    lines = [ln for ln in output.splitlines() if not ln.startswith(blocked_prefixes)]
    cleaned = "\n".join(lines).strip()
    if not cleaned:
        return ""
    try:
        wrapped = json.loads(cleaned)
    except json.JSONDecodeError:
        return cleaned
    if isinstance(wrapped, dict):
        response = wrapped.get("response")
        return response.strip() if isinstance(response, str) else cleaned
    return cleaned
