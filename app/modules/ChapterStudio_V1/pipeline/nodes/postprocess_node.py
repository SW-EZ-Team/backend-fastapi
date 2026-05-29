from __future__ import annotations

from app.modules.ChapterStudio_V1.common.errors import ConversionError
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState, StateRecord, StateRecords
from app.modules.ChapterStudio_V1.postprocess.pipeline import SlideInput, postprocess_all


async def postprocess_slides_node(state: ChapterStudioState) -> ChapterStudioState:
    """모델 HTML/CSS를 iframe 삽입 가능한 안전한 슬라이드로 후처리한다."""
    drafts = _records(state, "slide_drafts")
    processed = await postprocess_all([_slide_input(row) for row in drafts])
    return {"slides": [_slide_record(item) for item in processed]}


def _records(state: ChapterStudioState, key: str) -> StateRecords:
    value = state.get(key)
    if not isinstance(value, list):
        raise ConversionError(f"{key} 목록이 필요하다.")
    if not all(isinstance(item, dict) for item in value):
        raise ConversionError(f"{key} 항목은 dict여야 한다.")
    return value


def _slide_input(row: StateRecord) -> SlideInput:
    return {
        "index": _record_int(row, "slide_idx"),
        "category": _record_text(row, "category"),
        "html": _record_text(row, "html"),
        "css": _optional_text(row, "css"),
    }


def _slide_record(item: dict[str, object]) -> StateRecord:
    return {
        "slide_idx": _record_int(item, "index"),
        "html_content": _record_text(item, "iframe_html"),
        "category": _record_text(item, "category"),
        "warnings": item.get("warnings", []),
    }


def _record_text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or value == "":
        raise ConversionError(f"{key} 문자열이 필요하다.")
    return value


def _optional_text(row: StateRecord, key: str) -> str:
    value = row.get(key, "")
    if not isinstance(value, str):
        raise ConversionError(f"{key} 문자열이 필요하다.")
    return value


def _record_int(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int):
        raise ConversionError(f"{key} 정수가 필요하다.")
    return value


__all__ = ["postprocess_slides_node"]
