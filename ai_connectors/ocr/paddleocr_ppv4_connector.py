"""PaddleOCR PP-OCRv4 Korean OCRConnector 구현 (HTTP 클라이언트).

경로 A PoC — classical CNN 기반 OCR. PaddleOCR-VL(VLM, CER 75.9% 실패)과는
완전히 다른 모델 카테고리다.

설계 요점 — Nemotron-OCR-v2 커넥터와 동일 패턴:
 - OCRConnector Protocol 준수. recognize(OCRRequest) -> OCRResponse.
 - 네트워크 호출은 `_paddleocr_ppv4_http_client` 에, 응답 파싱은
   기존 `_nemotron_response_parser.parse_response` 를 재사용 (스키마가 호환됨).
 - vendor 오류는 전부 `ai_connectors.errors` 의 공유 예외로 정규화.
 - 타임아웃/재시도는 .env 로 오버라이드 (PADDLEOCR_PPV4_TIMEOUT_SEC, _RETRIES).
"""
from __future__ import annotations

import time

from ..errors import AIConnectorError
from ..schemas import OCRRequest, OCRResponse
from ._nemotron_response_parser import parse_response, require_dict
from ._paddleocr_ppv4_http_client import post_recognize

_DEFAULT_MODEL_NAME = "paddleocr-ppv4"


class PaddleOCRPPv4Connector:
    """PaddleOCR PP-OCRv4 Modal HTTP 클라이언트 커넥터.

    로컬 Mac 에는 가중치를 적재하지 않는다. 모든 추론은 원격 Modal L4 GPU 에서
    수행되고, 이 클래스는 `httpx.AsyncClient` 로 POST 만 보낸다.
    """

    name: str = _DEFAULT_MODEL_NAME

    async def recognize(self, req: OCRRequest) -> OCRResponse:
        """OCRRequest 를 받아 Modal 엔드포인트에 POST 하고 OCRResponse 로 돌려준다."""
        t0 = time.perf_counter()
        try:
            raw = await post_recognize(req.image_bytes)
        except AIConnectorError:
            raise
        except Exception as exc:
            raise AIConnectorError(f"PaddleOCR recognize 실패: {exc}") from exc
        latency_ms = (time.perf_counter() - t0) * 1000.0

        normalized = require_dict(raw)
        return parse_response(normalized, latency_ms=latency_ms)

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그."""
        return feature in {
            "korean",
            "english",
            "bbox",
            "modal",
            "http",
            "classical_ocr",
        }
