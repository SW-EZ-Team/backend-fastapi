"""PaddleOCR-VL 출력 파서 아톰 모듈.

VLM 출력 포맷:
  {text}<|LOC_x1|><|LOC_y1|><|LOC_x2|><|LOC_y1|><|LOC_x2|><|LOC_y2|><|LOC_x1|><|LOC_y2|>\\n

각 라인에서 LOC 토큰을 정규식으로 추출하고, 픽셀 좌표로 변환한 OCRDetection을 반환한다.
LOC 토큰이 없는 라인(Mode A, plain-text 모드)은 bbox=[0,0,0,0]으로 처리한다.
"""
from __future__ import annotations

import re

from ..schemas import OCRDetection

# LOC 토큰 추출 패턴 — 전역 컴파일로 재사용 성능 확보
_LOC_PATTERN = re.compile(r"<\|LOC_(\d+)\|>")

# 폴리곤 토큰 순서: x1,y1,x2,y1,x2,y2,x1,y2 (8개 — 시계방향 사각형)
# 필요한 인덱스: x1=0, y1=1, x2=2, y2=5
_IDX_X1, _IDX_Y1, _IDX_X2, _IDX_Y2 = 0, 1, 2, 5


def _loc_to_pixel(val: int, dim: int) -> int:
    """0-999 정규화 LOC 값을 픽셀 정수로 변환한다."""
    return int(val / 1000.0 * dim)


def _extract_bbox(loc_vals: list[int], width: int, height: int) -> list[int]:
    """LOC 값 리스트(8개)에서 [x1, y1, x2, y2] 픽셀 bbox를 추출한다.

    8개 미만인 경우 안전하게 [0,0,0,0]을 반환한다.
    """
    if len(loc_vals) < 6:
        return [0, 0, 0, 0]
    x1 = _loc_to_pixel(loc_vals[_IDX_X1], width)
    y1 = _loc_to_pixel(loc_vals[_IDX_Y1], height)
    x2 = _loc_to_pixel(loc_vals[_IDX_X2], width)
    y2 = _loc_to_pixel(loc_vals[_IDX_Y2], height)
    return [x1, y1, x2, y2]


def parse_vl_output(
    raw_text: str,
    width: int,
    height: int,
) -> list[OCRDetection]:
    """VLM 출력 문자열을 파싱하여 OCRDetection 목록을 반환한다.

    LOC 토큰이 있는 라인: bbox를 픽셀로 변환하고 confidence=1.0으로 고정한다.
    LOC 토큰이 없는 라인(plain-text 모드): bbox=[0,0,0,0]으로 채운다.
    빈 라인은 건너뛴다.
    """
    detections: list[OCRDetection] = []
    for line in raw_text.splitlines():
        loc_vals = [int(m) for m in _LOC_PATTERN.findall(line)]
        text = _LOC_PATTERN.sub("", line).strip()
        if not text:
            continue
        bbox = _extract_bbox(loc_vals, width, height) if loc_vals else [0, 0, 0, 0]
        detections.append(OCRDetection(text=text, bbox=bbox, confidence=1.0))
    return detections
