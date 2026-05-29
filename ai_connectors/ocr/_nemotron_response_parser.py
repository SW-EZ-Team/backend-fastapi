"""Nemotron-OCR-v2 응답 파서 원자 모듈.

Modal 엔드포인트가 반환한 vendor-specific JSON dict 를 공유
OCRResponse 스키마로 변환한다. 파싱 실패 시 InferenceError 로 정규화한다.

분리 이유 — HTTP 클라이언트(`_nemotron_http_client.py`)와 Protocol 조립부
(`nemotron_ocr_v2_connector.py`) 사이의 책임 경계를 명확히 하기 위함.
"""
from __future__ import annotations

from typing import Any

from ..errors import InferenceError
from ..schemas import OCRDetection, OCRResponse


def parse_response(
    raw: dict[str, Any],
    latency_ms: float,
) -> OCRResponse:
    """vendor JSON dict 를 OCRResponse 로 변환한다.

    기대 스키마:
      {
        "text": str,
        "detections": [{"bbox": [x1,y1,x2,y2], "text": str, "confidence": float}],
        "latency_ms": float,
        "model_version": str,
        "gpu_kind": str | None,
      }
    vendor 가 latency_ms 를 돌려주더라도 호출자 측 전체 지연(네트워크 포함)은
    `latency_ms` 파라미터로 덮어써서 레지스트리 계약을 유지한다.
    """
    detections = _parse_detections(raw.get("detections"))
    text = _resolve_text(raw, detections)
    model_version = _resolve_model_version(raw)
    return OCRResponse(
        detections=detections,
        text=text,
        model_version=model_version,
        latency_ms=latency_ms,
        page_count=1,
    )


def _parse_detections(raw_detections: Any) -> list[OCRDetection]:
    """detections 리스트를 OCRDetection 으로 변환한다.

    모델이 detection 을 반환하지 않거나 비어 있으면 빈 리스트를 돌려준다.
    각 항목이 dict 가 아니거나 bbox 길이가 4 가 아니면 건너뛴다.
    """
    if not isinstance(raw_detections, list):
        return []
    result: list[OCRDetection] = []
    for item in raw_detections:
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            bbox_int = [int(v) for v in bbox]
        except (TypeError, ValueError):
            continue
        text = _coerce_str(item.get("text", ""))
        confidence = _coerce_confidence(item.get("confidence", 0.0))
        result.append(
            OCRDetection(text=text, bbox=bbox_int, confidence=confidence),
        )
    return result


def _resolve_text(raw: dict[str, Any], detections: list[OCRDetection]) -> str:
    """text 필드가 있으면 그것을, 없으면 detections 를 이어붙여 반환한다.

    nemotron-ocr-v2 는 detection+recognition 분리 구조라 vendor 가 text 를
    집계해 돌려줄 수도 있고, detections 만 돌려줄 수도 있다. 양쪽 모두 커버한다.
    """
    text = raw.get("text")
    if isinstance(text, str) and text:
        return text
    return "\n".join(d.text for d in detections)


def _resolve_model_version(raw: dict[str, Any]) -> str:
    """모델 버전 문자열을 반환한다.

    vendor 가 model_version 을 넣어 보내면 그걸, 없으면 GPU 등급을 덧붙인
    고정 식별자를 반환한다. 벤치 리포트에서 GPU 등급 추적을 돕는다.
    """
    explicit = raw.get("model_version")
    if isinstance(explicit, str) and explicit:
        return explicit
    gpu_kind = raw.get("gpu_kind")
    if isinstance(gpu_kind, str) and gpu_kind:
        return f"nemotron-ocr-v2@{gpu_kind}"
    return "nemotron-ocr-v2"


def _coerce_str(value: Any) -> str:
    """임의 값을 str 로 강제 변환한다."""
    return value if isinstance(value, str) else str(value)


def _coerce_confidence(value: Any) -> float:
    """confidence 를 0~1 float 로 강제 변환한다.

    변환 실패 시 0.0 반환 — 벤치에서 confidence 가 0 이면 "미제공" 으로 해석하면 된다.
    """
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 0.0
    if conf < 0.0:
        return 0.0
    if conf > 1.0:
        return 1.0
    return conf


def require_dict(raw: Any) -> dict[str, Any]:
    """vendor 응답이 dict 임을 보장한다. 아니면 InferenceError 전파."""
    if not isinstance(raw, dict):
        raise InferenceError(
            f"Nemotron-OCR Modal 응답이 dict 가 아님: {type(raw).__name__}",
        )
    return raw
