"""시각 위주 슬라이드 미리보기 생성 모듈 — LLM 연동 래퍼."""
from __future__ import annotations

from app.modules.ChapterStudio_V1.app.llm_visual_gen import generate_visual_preview
from app.modules.ChapterStudio_V1.app.visual_demo_types import VisualPreviewResponse

__all__ = ["build_visual_preview"]


async def build_visual_preview(topic: str) -> VisualPreviewResponse:
    """주어진 주제에 대한 시각 위주 미리보기 전체 응답을 LLM으로 생성한다."""
    return await generate_visual_preview(topic)
