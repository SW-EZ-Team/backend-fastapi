"""Kanana Nano 2.1B Q4_K_M 기반 텔레그램 과제 캡션 생성 모듈.

사용법:
    from app.modules.AI_CPU_Kanana_Nano_Q4 import generate_caption, CaptionResult

    result = generate_caption(
        student_name="김민준",
        assignment_name="파이썬 리스트 컴프리헨션",
        weakness=None,
        deadline="내일 23:59",
    )
    print(result.text, result.source)   # source: "kanana" | "fallback"
"""
from .caption import generate_caption
from .caption import CaptionResult

__all__ = ["generate_caption", "CaptionResult"]
