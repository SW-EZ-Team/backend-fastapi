"""품질 점수 집계 — 네 개의 개별 지표를 가중 평균으로 합산한다.

가중치는 한국어 학술문서 OCR 실패 패턴 분석 결과를 반영한다.
문자 오염(30%)이 가장 치명적이고, 읽기 순서(25%)·표(25%)·수식(20%) 순이다.
"""
from __future__ import annotations

from .. import config as cfg

# 각 지표 가중치 — 합계 = 1.0
_W_CHAR = 0.30
_W_READ = 0.25
_W_TABLE = 0.25
_W_FORMULA = 0.20


def aggregate_page_quality(
    char: float,
    reading: float,
    table: float,
    formula: float,
) -> tuple[float, bool]:
    """네 품질 지표를 가중 평균해 최종 점수와 통과 여부를 반환한다.

    char 은 오염률(낮을수록 좋음)이므로 1.0 에서 뺀 값을 사용한다.
    나머지 세 지표는 높을수록 좋다.

    반환: (overall_score 0.0~1.0, passed: bool)
    """
    # 문자 오염률은 낮을수록 좋으므로 역수로 변환
    char_quality = 1.0 - char

    overall = (
        char_quality * _W_CHAR
        + reading * _W_READ
        + table * _W_TABLE
        + formula * _W_FORMULA
    )
    overall = min(max(overall, 0.0), 1.0)
    passed = overall >= cfg.quality_pass_threshold()
    return round(overall, 4), passed
