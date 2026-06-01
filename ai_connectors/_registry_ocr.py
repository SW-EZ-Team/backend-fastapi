"""OCR(광학 문자 인식) 커넥터 서브레지스트리.

OCR_CONNECTORS dict, 별칭 해소 헬퍼(_resolve_ocr_name), get_ocr_connector 팩토리를 담는다.
외부 코드는 이 파일을 직접 import 하지 않고 ai_connectors.registry 를 사용한다.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

from .base import OCRConnector
from .errors import ModelNotFoundError

_LOG = logging.getLogger(__name__)

# OCR 커넥터 팩토리 맵 (OCRConnector 구현체)
OCR_CONNECTORS: dict[str, Callable[[], OCRConnector]] = {}

try:
    from .ocr.gemini_ocr_connector import GeminiOCRConnector
    OCR_CONNECTORS["gemini-ocr"] = lambda: GeminiOCRConnector()
except ImportError as _gemini_ocr_import_err:
    _LOG.warning(
        "Gemini OCR 커넥터 등록 건너뜀 (ImportError: %s). "
        "`uv pip install google-genai` 실행 필요",
        _gemini_ocr_import_err,
    )

try:
    from .ocr.paddleocr_vl_mlx_connector import PaddleOCRVLMlxConnector
    OCR_CONNECTORS["paddleocr-vl-mlx"] = lambda: PaddleOCRVLMlxConnector()
except ImportError as _vl_import_err:
    _LOG.warning(
        "PaddleOCR-VL MLX 커넥터 등록 건너뜀 (ImportError: %s). "
        "`.venv-paddleocr-vl` 활성화 여부와 mlx-vlm 설치를 확인하세요.",
        _vl_import_err,
    )

# Nemotron-OCR-v2 Modal HTTP 커넥터 등록 — PaddleOCR-VL 대체용.
# httpx 만 요구하므로 mac 기본 venv 에서도 안전하게 import 된다.
try:
    from .ocr.nemotron_ocr_v2_connector import NemotronOCRv2Connector
    OCR_CONNECTORS["nemotron-ocr-v2"] = lambda: NemotronOCRv2Connector()
except ImportError as _nemotron_import_err:
    _LOG.warning(
        "Nemotron-OCR-v2 커넥터 등록 건너뜀 (ImportError: %s). "
        "`httpx` 패키지 설치 여부를 확인하세요.",
        _nemotron_import_err,
    )

# PaddleOCR PP-OCRv4 Korean Modal HTTP 커넥터 등록 — 경로 A PoC.
# classical CNN det+rec. PaddleOCR-VL(0.9B VLM)과는 무관한 다른 모델이다.
try:
    from .ocr.paddleocr_ppv4_connector import PaddleOCRPPv4Connector
    OCR_CONNECTORS["paddleocr-ppv4"] = lambda: PaddleOCRPPv4Connector()
except ImportError as _ppv4_import_err:
    _LOG.warning(
        "PaddleOCR PP-OCRv4 커넥터 등록 건너뜀 (ImportError: %s). "
        "`httpx` 패키지 설치 여부를 확인하세요.",
        _ppv4_import_err,
    )

# OCR 커넥터 shorthand 별칭 — 태스크 스펙의 AI_OCR 환경변수와 짧은 키를 모두 수용한다.
# 기본 레지스트리 키(`paddleocr-vl-mlx`, `nemotron-ocr-v2`)는 변경하지 않는다.
_OCR_ALIASES: dict[str, str] = {
    "nemotron_v2": "nemotron-ocr-v2",
    "nemotron-v2": "nemotron-ocr-v2",
    "paddleocr_vl": "paddleocr-vl-mlx",
    "paddleocr-vl": "paddleocr-vl-mlx",
    # 경로 A 호출 축약어 — task spec 의 AI_OCR shorthand 수용
    "paddleocr_ppv4": "paddleocr-ppv4",
    "paddleocr-pp-v4": "paddleocr-ppv4",
    "pp-ocrv4": "paddleocr-ppv4",
    "gemini_ocr": "gemini-ocr",
}


def _resolve_ocr_name(model_name: str | None) -> str:
    """AI_MODEL_OCR(공식) > AI_OCR(shorthand) > 기본값 순서로 이름을 해소한다.

    단순 위임 함수지만 레지스트리 분기 로직을 한 곳에 모아두기 위해 분리했다.
    """
    if model_name:
        return _OCR_ALIASES.get(model_name, model_name)
    # AI_MODEL_OCR 가 있으면 우선 사용, 없을 때만 shorthand AI_OCR 를 돌아본다.
    primary = os.getenv("AI_MODEL_OCR", "").strip()
    if primary:
        return _OCR_ALIASES.get(primary, primary)
    shorthand = os.getenv("AI_OCR", "").strip()
    if shorthand:
        return _OCR_ALIASES.get(shorthand, shorthand)
    # PoC 안전 기본값 — 기존 PaddleOCR-VL 경로를 유지한다.
    return "paddleocr-vl-mlx"


def get_ocr_connector(model_name: str | None = None) -> OCRConnector:
    """.env 의 AI_MODEL_OCR(또는 AI_OCR) / 명시된 model_name 으로 OCR 커넥터 반환."""
    name = _resolve_ocr_name(model_name)
    if name not in OCR_CONNECTORS:
        raise ModelNotFoundError(
            f"Unknown OCR model: {name}. "
            f"Registered: {list(OCR_CONNECTORS.keys())}. "
            f"AI_MODEL_OCR(또는 AI_OCR) 환경변수와 venv 활성화 여부를 확인하세요.",
        )
    return OCR_CONNECTORS[name]()
