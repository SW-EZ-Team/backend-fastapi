"""TTS V2 — 입력 로드 노드.

input_type 을 자동 판별하고, 적절한 어댑터를 호출해 sections 목록을 생성한다.
raw_text 와 file_content 가 둘 다 있을 때는 file_content 가 우선한다.
"""
from __future__ import annotations

import logging
import time

from app.modules.TTS_V2.processors.input_adapter import (
    read_file_input,
    read_markdown_input,
    read_text_input,
)
from app.modules.TTS_V2.schemas.state import AudiobookState

_LOG = logging.getLogger(__name__)


def _detect_input_type(raw_text: str) -> str:
    """마크다운 헤딩(#)이 포함된 텍스트는 'markdown', 그 외는 'text' 로 판별한다."""
    for line in raw_text.splitlines():
        if line.lstrip().startswith("#"):
            return "markdown"
    return "text"


def _parse_sections(state: AudiobookState) -> tuple[str, list[dict]]:
    """state 에서 input_type 과 sections 를 결정해 반환한다.

    우선순위: file_content > raw_text (markdown) > raw_text (text).
    """
    file_content: str | None = state.get("file_content")
    raw_text: str | None = state.get("raw_text")

    if file_content:
        return "file", read_file_input(file_content, ".txt")

    if raw_text:
        detected = _detect_input_type(raw_text)
        if detected == "markdown":
            return "markdown", read_markdown_input(raw_text)
        return "text", read_text_input(raw_text)

    # 빈 입력 — 빈 섹션으로 계속 진행한다
    return "text", []


def load_input_node(state: AudiobookState) -> dict:
    """입력 텍스트를 파싱해 sections 리스트를 생성한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환
    if state.get("pipeline_status") == "error":
        return {}
    t_start = time.monotonic()
    try:
        input_type, sections = _parse_sections(state)
    except Exception as exc:
        _LOG.error("입력 파싱 중 오류 발생: %s", exc)
        return {
            "pipeline_status": "error",
            "error_message": f"입력 파싱 중 오류: {exc}",
        }

    # 빈 입력은 최종 merge 에서 빈 오디오가 나오므로 앞단에서 명시적으로 종료
    if not sections:
        _LOG.warning("입력 텍스트가 비어 있거나 섹션 추출 불가 — 파이프라인 종료")
        return {
            "pipeline_status": "error",
            "error_message": "입력 텍스트가 비어 있거나 섹션을 추출할 수 없음",
        }

    elapsed_ms = (time.monotonic() - t_start) * 1000
    timings = {**state.get("timings", {}), "load_input": elapsed_ms}
    return {
        "input_type": input_type,
        "sections": sections,
        "current_phase": "loading",
        "pipeline_status": "loading",
        "timings": timings,
    }
