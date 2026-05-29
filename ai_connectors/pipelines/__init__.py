"""AI 파이프라인 패키지.

개별 커넥터(OCR, postproc 등)를 조합해 복합 처리 흐름을 구성하는
오케스트레이터 모듈을 담는다.
"""
from .textbook_ocr_pipeline import TextbookOCRPipeline

__all__ = ["TextbookOCRPipeline"]
