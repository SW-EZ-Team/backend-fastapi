from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.app.curriculum_preview import build_curriculum_preview
from app.modules.ChapterStudio_V1.app.curriculum_preview_types import CurriculumPreviewRequest
from app.modules.ChapterStudio_V1.app.demo_agent import demo_agent_steps, run_demo_agent
from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput
from app.modules.ChapterStudio_V1.app.frontend_payload import frontend_preview_payload
from app.modules.ChapterStudio_V1.app.frontend_contract import DepthLevel, SourceMode, TeacherId, contract
from app.modules.ChapterStudio_V1.app.reference_books.preview import ReferenceBookPreviewRequest, build_reference_book_preview
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext
from app.modules.ChapterStudio_V1.app.slide_chat_context import build_demo_chat_context
from app.modules.ChapterStudio_V1.app.slide_chat_responder import stream_chat_response
from app.modules.ChapterStudio_V1.app.slide_chat_types import SlideChatRequest
from app.modules.ChapterStudio_V1.app.visual_demo import build_visual_preview
from app.modules.ChapterStudio_V1.app.visual_demo_types import VisualPreviewResponse
from app.modules.ChapterStudio_V1.common.errors import ConversionError

router = APIRouter(prefix="/demo/chapter-studio", tags=["demo"])
_HTML_PATH = Path(__file__).resolve().parents[2] / "tests" / "manual" / "chapter_studio_demo.html"
_CHAT_HTML_PATH = Path(__file__).resolve().parents[2] / "tests" / "manual" / "chapter_studio_chat_demo.html"
_CURRICULUM_HTML_PATH = Path(__file__).resolve().parents[2] / "tests" / "manual" / "chapter_studio_curriculum_demo.html"
_VISUAL_CMP_HTML_PATH = Path(__file__).resolve().parents[2] / "tests" / "manual" / "chapter_studio_visual_compare.html"
_REFERENCE_HTML_PATH = Path(__file__).resolve().parents[2] / "tests" / "manual" / "chapter_studio_reference_book_demo.html"
DemoEngine = Literal["mock", "codex_cli"]
DemoTemplate = str


@router.get("", response_class=HTMLResponse)
async def demo_page() -> HTMLResponse:
    """수동 테스트 HTML을 FastAPI에서 바로 열 수 있게 제공한다."""
    return HTMLResponse(_HTML_PATH.read_text(encoding="utf-8"))


@router.get("/chat", response_class=HTMLResponse)
async def demo_chat_page() -> HTMLResponse:
    """슬라이드 채팅 수동 테스트 HTML을 제공한다."""
    return HTMLResponse(_CHAT_HTML_PATH.read_text(encoding="utf-8"))


@router.get("/curriculum", response_class=HTMLResponse)
async def demo_curriculum_page() -> HTMLResponse:
    """CourseDetail 흐름과 맞춘 커리큘럼 초안 미리보기 HTML을 제공한다."""
    return HTMLResponse(_CURRICULUM_HTML_PATH.read_text(encoding="utf-8"))


@router.get("/visual-compare", response_class=HTMLResponse)
async def demo_visual_compare_page() -> HTMLResponse:
    """텍스트 위주 vs 시각 위주 출력 비교 테스트 HTML을 제공한다."""
    return HTMLResponse(_VISUAL_CMP_HTML_PATH.read_text(encoding="utf-8"))


@router.get("/reference-book", response_class=HTMLResponse)
async def demo_reference_book_page() -> HTMLResponse:
    """참고도서 OCR 컨텍스트 수동 테스트 HTML을 제공한다."""
    return HTMLResponse(_REFERENCE_HTML_PATH.read_text(encoding="utf-8"))


@router.get("/visual-preview", response_model=VisualPreviewResponse, response_model_by_alias=True)
async def demo_visual_preview(
    topic: str = Query(min_length=1, max_length=80),
) -> VisualPreviewResponse:
    """같은 주제에 대한 시각 위주 출력 미리보기 JSON을 반환한다."""
    return await build_visual_preview(topic)


@router.get("/contract")
async def demo_contract() -> object:
    """프론트 초안이 연결할 수 있는 입력 계약을 제공한다."""
    return contract()


@router.get("/frontend-preview")
async def demo_frontend_preview(
    topic: str = Query(min_length=1, max_length=80),
    template: DemoTemplate = Query(default="auto"),
) -> object:
    """frontend-web의 빈 iframe srcDoc 삽입 계약을 바로 검증한다."""
    data = DemoGenerationInput(topic=topic)
    return frontend_preview_payload(await run_demo_agent(data, 5, "mock", template))


@router.post("/chat/context")
async def demo_chat_context(req: SlideChatRequest) -> object:
    """현재 슬라이드 질문에 들어갈 압축 컨텍스트를 확인한다."""
    return build_demo_chat_context(req).model_dump()


@router.post("/chat/stream")
async def demo_chat_stream(req: SlideChatRequest) -> StreamingResponse:
    """현재 슬라이드 컨텍스트 기반 채팅 답변을 스트리밍한다."""
    ctx = build_demo_chat_context(req)
    return StreamingResponse(stream_chat_response(req, ctx), media_type="text/plain; charset=utf-8")


@router.post("/curriculum/preview")
async def demo_curriculum_preview(req: CurriculumPreviewRequest) -> object:
    """운영의 커리큘럼 생성 화면에 넣을 초안 응답을 검증한다."""
    return (await build_curriculum_preview(req)).model_dump()


@router.post("/reference-book/context-preview", response_model=ReferenceBookContext)
async def demo_reference_book_context_preview(req: ReferenceBookPreviewRequest) -> ReferenceBookContext:
    """OCR 페이지 결과가 어떤 참고도서 컨텍스트로 줄어드는지 확인한다."""
    return build_reference_book_preview(req)


@router.get("/stream")
async def demo_stream(
    topic: str = Query(min_length=1, max_length=80),
    slide_count: int = Query(default=5, ge=5, le=5),
    engine: DemoEngine = Query(default="mock"),
    template: DemoTemplate = Query(default="concept_code"),
    source_mode: SourceMode = Query(default="topic"),
    pdf_file_name: str = Query(default="", max_length=160),
    duration_days: int = Query(default=30, ge=1, le=365),
    depth: DepthLevel = Query(default="normal"),
    teacher: TeacherId = Query(default="owl"),
    tone: int = Query(default=50, ge=0, le=100),
    pace: int = Query(default=50, ge=0, le=100),
    tutor_depth: int = Query(default=50, ge=0, le=100),
    socratic: int = Query(default=70, ge=0, le=100),
    audience_level: str = Query(default="일반 학습자", max_length=80),
    learning_goal: str = Query(default="핵심 개념 이해와 실습", max_length=160),
    weak_points: str = Query(default="", max_length=240),
    chapter_title: str = Query(default="데모 챕터", max_length=120),
    chapter_brief: str = Query(default="", max_length=400),
) -> StreamingResponse:
    """EventSource로 pipeline 진행과 최종 결과를 흘려보낸다."""
    data = DemoGenerationInput(
        topic=topic,
        source_mode=source_mode,
        pdf_file_name=pdf_file_name,
        duration_days=duration_days,
        depth=depth,
        teacher=teacher,
        tone=tone,
        pace=pace,
        tutor_depth=tutor_depth,
        socratic=socratic,
        audience_level=audience_level,
        learning_goal=learning_goal,
        weak_points=weak_points,
        chapter_title=chapter_title,
        chapter_brief=chapter_brief,
    )
    return StreamingResponse(_event_stream(data, slide_count, engine, template), media_type="text/event-stream")


async def _event_stream(
    data: DemoGenerationInput, slide_count: int, engine: DemoEngine, template: DemoTemplate
) -> AsyncIterator[str]:
    for step in demo_agent_steps(engine):
        yield _sse("node_complete", {"node": step})
        await asyncio.sleep(0)
    try:
        result = await _build_result(data, slide_count, engine, template)
    except (ConnectorError, ConversionError, RuntimeError) as exc:
        yield _sse("error", {"message": str(exc)})
        return
    yield _sse("complete", result)


async def _build_result(
    data: DemoGenerationInput, slide_count: int, engine: DemoEngine, template: DemoTemplate
) -> object:
    return await run_demo_agent(data, slide_count, engine, template)


def _sse(event: str, payload: object) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
