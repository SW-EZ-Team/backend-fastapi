"""OpenAI OCR 폴백 커넥터.

Gemini OCR 커넥터(gemini_ocr_connector.py)와 동일한 공개 인터페이스
(recognize / supports)와 OCRResponse 스키마를 제공한다. Gemini OCR 장애 시
도메인 폴백 래퍼가 이 커넥터로 회로를 넘긴다. 동기 SDK 를 asyncio.to_thread 로
감싸 블로킹을 막는다(Gemini OCR 와 동일한 래핑 전략).
"""
from __future__ import annotations

import asyncio
import base64
import os
import time

from .._openai_common import build_openai_client
from ..errors import AIConnectorError, InferenceError
from ..schemas import OCRRequest, OCRResponse

_DEFAULT_MODEL = "gpt-5.5"
# Gemini OCR 와 동일한 프롬프트/시스템 지시를 그대로 재사용해 출력 형식을 일치시킨다.
_PROMPT = (
    "이미지의 모든 텍스트를 읽기 순서대로 마크다운으로 추출. "
    "표는 마크다운 표로. 부연설명·서론·결론 없이 본문만 출력."
)
_SYSTEM_INSTRUCTION = (
    "너는 정밀 OCR 엔진이다. 추출한 텍스트만 출력하고 어떤 설명도 붙이지 않는다."
)


class OpenAIOCRConnector:
    """OpenAI 비전 입력을 기존 OCRResponse 로 변환한다."""

    name: str = "openai-ocr"

    async def recognize(self, req: OCRRequest) -> OCRResponse:
        """이미지 바이트에서 읽기 순서 마크다운 텍스트를 추출한다."""
        started_at = time.perf_counter()
        try:
            markdown = await asyncio.to_thread(self._recognize_markdown, req.image_bytes)
        except AIConnectorError:
            raise
        except Exception as exc:
            raise InferenceError(f"OpenAI OCR 호출 실패: {exc}") from exc
        return OCRResponse(
            detections=[],
            text=markdown,
            model_version=self.name,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            page_count=1,
        )

    def supports(self, feature: str) -> bool:
        """OpenAI OCR 기능 플래그를 반환한다(Gemini OCR 와 동일 집합)."""
        return feature in {"korean", "english", "markdown", "table", "multimodal"}

    def _recognize_markdown(self, image_bytes: bytes) -> str:
        """동기 openai 호출을 실행하고 마크다운 본문만 반환한다."""
        client, _openai = build_openai_client()
        model = os.getenv("OPENAI_OCR_MODEL", _DEFAULT_MODEL)
        data_url = _to_data_url(image_bytes)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_INSTRUCTION},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            temperature=0.0,
        )
        text = _first_message_text(resp)
        return text.strip()


def _to_data_url(image_bytes: bytes) -> str:
    """이미지 바이트를 chat.completions 비전 입력용 base64 data URL 로 변환한다."""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _first_message_text(resp: object) -> str:
    """첫 번째 choice 의 message.content 를 추출한다."""
    choices = getattr(resp, "choices", None)
    if not choices:
        raise InferenceError("OpenAI OCR 응답에서 choices 를 찾지 못했습니다.")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        raise InferenceError("OpenAI OCR 응답에서 text 를 찾지 못했습니다.")
    return content
