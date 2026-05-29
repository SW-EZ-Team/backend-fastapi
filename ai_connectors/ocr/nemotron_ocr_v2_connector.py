"""NVIDIA Nemotron-OCR-v2 OCRConnector 구현 (HTTP 클라이언트 형태).

PaddleOCR-VL 이 페이지 CER 75.9% 로 배포 불가 판정을 받아 교체된 OCR 모델이다.
로컬 Mac 은 CUDA 미지원이라 직접 추론이 불가능해 Modal GPU 엔드포인트를 HTTP 로
호출하는 클라이언트 커넥터 구조를 택했다. 후처리(Kanana-2)는 제거했다 —
글자 추출만 수행하고 정확도는 하위 LLM 이 커버한다는 전략이다.

설계 요점:
 - OCRConnector Protocol 준수. recognize(OCRRequest) -> OCRResponse.
 - 네트워크 호출은 `_nemotron_http_client` 에, 응답 파싱은 `_nemotron_response_parser` 에 분리.
 - vendor-specific 오류는 전부 `ai_connectors.errors` 의 공유 예외로 정규화된다.
 - 타임아웃/재시도는 .env 로 오버라이드 가능 (NEMOTRON_OCR_TIMEOUT_SEC, NEMOTRON_OCR_RETRIES).
"""
from __future__ import annotations

import time

from ..errors import AIConnectorError
from ..schemas import OCRRequest, OCRResponse
from ._nemotron_http_client import post_recognize
from ._nemotron_response_parser import parse_response, require_dict

# 버전 식별자 — 실제 model_version 은 vendor 응답에서 GPU 등급 포함해 결정된다
_DEFAULT_MODEL_NAME = "nemotron-ocr-v2"


class NemotronOCRv2Connector:
    """Nemotron-OCR-v2 Modal HTTP 클라이언트 커넥터.

    로컬 Mac 에는 가중치를 적재하지 않는다. 모든 추론은 원격 Modal 엔드포인트에서
    수행되고, 이 클래스는 `httpx.AsyncClient` 로 POST 만 보낸다.
    인스턴스 자체는 상태를 가지지 않아 재생성 비용이 거의 없다.
    """

    name: str = _DEFAULT_MODEL_NAME

    async def recognize(self, req: OCRRequest) -> OCRResponse:
        """OCRRequest 를 받아 Modal 엔드포인트에 POST 하고 OCRResponse 로 돌려준다.

        전체 round-trip 지연(네트워크 + vendor 추론)을 latency_ms 로 집계한다.
        vendor 가 자체 latency 를 돌려주더라도 호출자 관점의 체감 지연을
        쓰는 쪽이 예산/비용 추정에 더 유용하다.
        """
        t0 = time.perf_counter()
        try:
            raw = await post_recognize(req.image_bytes)
        except AIConnectorError:
            # 이미 공유 예외로 정규화된 오류는 그대로 전파한다.
            raise
        except Exception as exc:
            # 예상치 못한 예외만 AIConnectorError 로 감싸 올린다.
            raise AIConnectorError(f"Nemotron-OCR recognize 실패: {exc}") from exc
        latency_ms = (time.perf_counter() - t0) * 1000.0

        normalized = require_dict(raw)
        return parse_response(normalized, latency_ms=latency_ms)

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그를 반환한다.

        layout_analysis / latex_preserve 는 지원하지 않는다 — 본 모델은 글자 추출 전용이다.
        """
        return feature in {
            "korean",
            "english",
            "multilingual",
            "bbox",
            "modal",
            "http",
        }
