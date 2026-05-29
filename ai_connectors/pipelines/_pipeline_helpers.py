"""파이프라인 공용 원자 헬퍼.

오케스트레이터에서 분리된 순수 함수들.
각 함수는 단일 책임을 가지며 외부 인프라를 직접 import 하지 않는다.
"""
from __future__ import annotations

from ai_connectors.pipeline_schemas import PageResult
from ai_connectors.schemas import Correction, OCRResponse

# 페이지 텍스트 구분자 — 집계 시 각 페이지 사이에 삽입
_PAGE_SEP = f"\n{'─' * 40}\n"


def build_page_result(page_num: int, ocr_resp: OCRResponse) -> PageResult:
    """OCR 단일 페이지 응답을 PageResult 스키마로 변환한다."""
    return PageResult(
        page_num=page_num,
        text=ocr_resp.text,
        detections=list(ocr_resp.detections),
    )


def aggregate_plain_text(pages: list[PageResult]) -> str:
    """페이지 목록의 텍스트를 구분자로 이어붙여 전체 텍스트를 만든다."""
    texts = [p.text for p in pages if p.text]
    return _PAGE_SEP.join(texts)


def parse_corrections(
    raw_corrections: list[Correction | dict[str, str]],
) -> list[Correction]:
    """커넥터가 반환한 Correction 인스턴스 또는 dict 목록을 Correction 목록으로 변환한다.

    PostprocResponse.corrections 는 list[Correction] 이므로 Correction 인스턴스를
    우선 처리하고, 하위 호환 목적으로 dict 도 수용한다.
    """
    result: list[Correction] = []
    for item in raw_corrections:
        if isinstance(item, Correction):
            # PostprocResponse 에서 넘어온 Pydantic 인스턴스 — 그대로 사용
            if item.original and item.corrected:
                result.append(item)
        else:
            # dict 형태 — 이전 str-in 규약 잔재 또는 외부 주입 데이터
            original = item.get("original", "")
            corrected = item.get("corrected", "")
            if original and corrected:
                result.append(
                    Correction(
                        original=original,
                        corrected=corrected,
                        reason=item.get("reason", ""),
                    )
                )
    return result
