"""품질 검사 패키지 — 페이지 품질 집계 함수를 re-export한다."""
from __future__ import annotations

from .aggregate import aggregate_page_quality
from .classifier import classify_pages

__all__ = ["aggregate_page_quality", "classify_pages"]
