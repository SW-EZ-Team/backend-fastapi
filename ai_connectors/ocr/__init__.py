"""OCR 커넥터 서브 패키지.

각 런타임(Gemini 클라우드 OCR, Nemotron-OCR-v2 Modal HTTP, PaddleOCR PP-OCRv4 등)별로
파일 하나. 등록은 상위 `ai_connectors.registry.OCR_CONNECTORS`에서 수행한다.

활성 기본값은 클라우드 `gemini-ocr` 이며, `.env` 의 `AI_MODEL_OCR` 로 다른 경로를
명시 선택할 수 있다(예: nemotron-ocr-v2).
"""

from .nemotron_ocr_v2_connector import NemotronOCRv2Connector

__all__ = [
    "NemotronOCRv2Connector",
]
