"""후처리 패키지 — 마크다운 정제 함수를 re-export하고 전체 파이프라인을 제공한다.

각 함수는 순수 함수이므로 순서를 바꾸거나 단독으로 사용할 수 있다.
기본 실행 순서는 OCR 출력물에서 잡음을 제거하는 최적 순서로 결정되었다.
"""
from __future__ import annotations

from .formula_convert import extract_latex_blocks
from .header_footer import remove_headers_footers
from .hyphen_restore import restore_hyphens
from .paragraph_merge import merge_paragraphs
from .table_convert import normalize_tables

__all__ = [
    "remove_headers_footers",
    "restore_hyphens",
    "merge_paragraphs",
    "normalize_tables",
    "extract_latex_blocks",
    "run_all",
]


async def run_all(markdown: str) -> str:
    """전체 후처리 파이프라인을 순서대로 실행한다.

    각 단계는 동기 순수 함수이므로 await 없이 연속 호출한다.
    LangGraph 노드에서 비동기 컨텍스트로 호출하기 위해 async 로 선언한다.
    """
    result = remove_headers_footers(markdown)
    result = restore_hyphens(result)
    result = merge_paragraphs(result)
    result = normalize_tables(result)
    result = extract_latex_blocks(result)
    return result
