from __future__ import annotations

import json
import re
from typing import Any

from app.modules.ChapterStudio_V1.ai_connectors.gemini_cli_connector import GeminiCLIConnector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.common.config import (
    claude_sonnet_api_key,
    claude_sonnet_model,
    gemini_api_key,
    gemini_cli_model,
)


async def run_gemini_cli_live_probe(prompt: str) -> dict[str, Any]:
    """Gemini CLI를 실제 호출하고 외부 API 키 상태는 값 노출 없이 점검한다."""
    connector = GeminiCLIConnector()
    response = await connector.generate(
        ChapterAIRequest(
            system=(
                "너는 ChapterStudio_V1 라이브 연결 점검기다. "
                "한국어 JSON 객체 한 개만 출력한다. "
                "키는 ok, topic, summary, next_check 네 개만 사용한다."
            ),
            user=prompt,
            max_tokens=512,
            temperature=0.0,
            extra={},
        )
    )
    parsed_response = _parse_response_json(response.text)
    return {
        "ok": bool(response.text.strip()),
        "connector": connector.name,
        "configured_model": gemini_cli_model(),
        "observed_model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "finish_reason": response.finish_reason,
        "response_text": response.text,
        "response_json_valid": parsed_response is not None,
        "response_json": parsed_response,
        "gemini_api_key_available": gemini_api_key() is not None,
        "claude_sonnet_key_available": claude_sonnet_api_key() is not None,
        "claude_sonnet_model": claude_sonnet_model(),
        "secret_value_printed": False,
    }


def _parse_response_json(text: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
