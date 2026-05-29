from __future__ import annotations

import asyncio
import json
from asyncio.subprocess import DEVNULL, PIPE
from collections.abc import Mapping
from typing import Any

from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError, TimeoutError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.common.config import gemini_cli_max_concurrency, gemini_cli_model, gemini_cli_timeout_sec


class GeminiCLIConnector:
    """Gemini CLI 래퍼 커넥터 — OAuth 인증 상태를 그대로 활용한다."""

    name = "gemini_cli"

    def __init__(self, command: str = "gemini") -> None:
        self._command = command

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """Gemini CLI OAuth/인증 상태를 그대로 쓰고 JSON stdout만 정규화한다."""
        stdout, stderr, returncode = await self._run(self._build_command(req))
        if returncode != 0:
            raise ConnectorError(_failure_message(stdout, stderr))
        payload = _extract_cli_payload(stdout)
        text = _response_text(payload)
        input_tokens, output_tokens = _token_pair(payload, req.user, text)
        return ChapterAIResponse(
            text=text,
            model=_model_name(payload),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason="stop",
        )

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        """CLI 프로세스 폭주를 막기 위해 작은 semaphore로만 병렬화한다."""
        if not reqs:
            return []
        semaphore = asyncio.Semaphore(gemini_cli_max_concurrency())

        async def guarded(req: ChapterAIRequest) -> ChapterAIResponse:
            async with semaphore:
                return await self.generate(req)

        return list(await asyncio.gather(*[guarded(req) for req in reqs]))

    def supports(self, feature: str) -> bool:
        return feature in {"gemini_cli", "local_dev", "json_mode", "batch", "voice_quality_repair"}

    def _build_command(self, req: ChapterAIRequest) -> list[str]:
        return [
            self._command,
            "--skip-trust",
            "--approval-mode",
            "plan",
            "--output-format",
            "json",
            "--model",
            gemini_cli_model(),
            "-p",
            _compose_prompt(req),
        ]

    async def _run(self, command: list[str]) -> tuple[str, str, int]:
        """CLI 서브프로세스를 실행하고 (stdout, stderr, returncode) 를 반환한다."""
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=DEVNULL,
                stdout=PIPE,
                stderr=PIPE,
            )
        except OSError as exc:
            raise ConnectorError(f"gemini_cli 실행 실패: {exc}") from exc
        return await _communicate(process, gemini_cli_timeout_sec())


async def _communicate(
    process: asyncio.subprocess.Process, timeout_sec: int
) -> tuple[str, str, int]:
    """프로세스 통신 + 타임아웃 처리."""
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=timeout_sec
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise TimeoutError(f"gemini_cli {timeout_sec}초 초과") from exc
    return (
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
        process.returncode or 0,
    )


def _compose_prompt(req: ChapterAIRequest) -> str:
    """시스템 프롬프트와 사용자 요청을 병합한다."""
    system = req.system.strip()
    if not system:
        return req.user
    return f"{system}\n\n사용자 요청:\n{req.user}"


def _extract_cli_payload(stdout: str) -> dict[str, Any]:
    """stdout 에서 첫 번째 JSON 객체를 추출한다."""
    value = _decode_json_object(stdout)
    if not isinstance(value, dict):
        raise ConnectorError("gemini_cli 출력이 객체가 아니다.")
    return value


def _decode_json_object(text: str) -> Any:
    """텍스트에서 첫 JSON 객체를 찾아 파싱한다."""
    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(value, dict):
            return value
    if "{" not in text:
        raise ConnectorError("gemini_cli stdout에서 JSON 객체를 찾지 못했다.")
    detail = f": {last_error}" if last_error is not None else ""
    raise ConnectorError(f"gemini_cli stdout JSON 객체 파싱 실패{detail}")


def _response_text(payload: Mapping[str, Any]) -> str:
    """응답 JSON 에서 response 텍스트를 추출한다."""
    response = payload.get("response")
    if not isinstance(response, str) or not response.strip():
        raise ConnectorError("gemini_cli 응답에서 response 문자열을 찾지 못했다.")
    return response


def _model_name(payload: Mapping[str, Any]) -> str:
    """응답 stats 에서 실제 사용된 모델 이름을 추출한다."""
    stats = payload.get("stats")
    if isinstance(stats, Mapping):
        models = stats.get("models")
        if isinstance(models, Mapping) and models:
            first = next(iter(models.keys()))
            if isinstance(first, str):
                return first
    return gemini_cli_model()


def _token_pair(
    payload: Mapping[str, Any], prompt: str, response: str
) -> tuple[int, int]:
    """stats 에서 토큰 수를 추출하고, 실패 시 길이 기반 추정치를 반환한다."""
    stats = payload.get("stats")
    if isinstance(stats, Mapping):
        models = stats.get("models")
        if isinstance(models, Mapping) and models:
            first_model = next(iter(models.values()))
            if isinstance(first_model, Mapping):
                tokens = first_model.get("tokens")
                if isinstance(tokens, Mapping):
                    input_tokens = _int_field(tokens, "input") or _int_field(tokens, "prompt")
                    output_tokens = _int_field(tokens, "candidates")
                    if input_tokens is not None and output_tokens is not None:
                        return input_tokens, output_tokens
    return max(len(prompt) // 4, 0), max(len(response) // 4, 0)


def _int_field(data: Mapping[str, Any], key: str) -> int | None:
    """dict 에서 int 값을 안전하게 추출한다."""
    value = data.get(key)
    return value if isinstance(value, int) else None


def _failure_message(stdout: str, stderr: str) -> str:
    """에러 메시지를 정리해 반환한다."""
    detail = stderr.strip() or stdout.strip() or "원인 없음"
    return f"gemini_cli 비정상 종료: {detail[-800:]}"
