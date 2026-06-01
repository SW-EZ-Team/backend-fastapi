"""Gemini OCR 커넥터."""
from __future__ import annotations

import asyncio
import os
import time

from .._gemini_common import build_genai_client
from ..errors import AIConnectorError, InferenceError
from ..schemas import OCRRequest, OCRResponse

_DEFAULT_MODEL = "gemini-2.5-flash"
_PROMPT = (
    "이미지의 모든 텍스트를 읽기 순서대로 마크다운으로 추출. "
    "표는 마크다운 표로. 부연설명·서론·결론 없이 본문만 출력."
)
_SYSTEM_INSTRUCTION = (
    "너는 정밀 OCR 엔진이다. 추출한 텍스트만 출력하고 어떤 설명도 붙이지 않는다."
)


class GeminiOCRConnector:
    """Gemini 이미지 입력을 기존 OCRResponse 로 변환한다."""

    name: str = "gemini-ocr"

    async def recognize(self, req: OCRRequest) -> OCRResponse:
        """이미지 바이트에서 읽기 순서 마크다운 텍스트를 추출한다."""
        started_at = time.perf_counter()
        try:
            markdown = await asyncio.to_thread(self._recognize_markdown, req.image_bytes)
        except AIConnectorError:
            raise
        except Exception as exc:
            raise InferenceError(f"Gemini OCR 호출 실패: {exc}") from exc
        return OCRResponse(
            detections=[],
            text=markdown,
            model_version=self.name,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            page_count=1,
        )

    def supports(self, feature: str) -> bool:
        """Gemini OCR 기능 플래그를 반환한다."""
        return feature in {"korean", "english", "markdown", "table", "multimodal"}

    def _recognize_markdown(self, image_bytes: bytes) -> str:
        """동기 google-genai 호출을 실행하고 마크다운 본문만 반환한다."""
        client, genai = build_genai_client()
        model = os.getenv("GEMINI_OCR_MODEL", _DEFAULT_MODEL)
        resp = client.models.generate_content(
            model=model,
            contents=[
                genai.types.Part.from_bytes(
                    data=image_bytes,
                    mime_type="image/png",
                ),
                _PROMPT,
            ],
            config=genai.types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                temperature=0.0,
            ),
        )
        text = getattr(resp, "text", None)
        if not isinstance(text, str):
            raise InferenceError("Gemini OCR 응답에서 text 를 찾지 못했습니다.")
        return text.strip()
