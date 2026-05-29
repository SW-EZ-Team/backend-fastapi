"""OCR 커넥터 서브 패키지.

각 런타임(PaddleOCR-VL MLX GPU, Nemotron-OCR-v2 Modal HTTP 등)별로 파일 하나.
등록은 상위 `ai_connectors.registry.OCR_CONNECTORS`에서 수행한다.

PoC 단계 메모 — PaddleOCR-VL-1.5 와 Nemotron-OCR-v2 가 공존한다. 기본값은 여전히
`paddleocr-vl-mlx` 로, 실사용자가 `.env` 에서 `AI_MODEL_OCR=nemotron-ocr-v2` 로
명시 전환할 때만 Nemotron 경로가 활성된다.
"""

from .nemotron_ocr_v2_connector import NemotronOCRv2Connector
from .paddleocr_vl_mlx_connector import PaddleOCRVLMlxConnector

__all__ = [
    "NemotronOCRv2Connector",
    "PaddleOCRVLMlxConnector",
]
