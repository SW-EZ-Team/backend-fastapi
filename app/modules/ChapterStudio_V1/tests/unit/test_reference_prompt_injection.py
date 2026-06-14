"""PDF 참고도서 발췌가 실제 생성 프롬프트에 도달하는지 검증한다.

검증 체인 3종:
1. 강의 병렬 경로 — GenerationContext.reference_book_context → state.reference_context_prompt
   → 병렬 컴포넌트 요청 5종(slides/quizzes/note/assignment/voice)의 최종 프롬프트 문자열.
2. 강의 단일콜 경로 — 같은 state로 build_generation_request 프롬프트.
3. 커리큘럼 경로 — course.source_pdf_url → Qdrant 발췌(_pdf_excerpt_block) → 슬롯-루프 프롬프트.

PDF 없는(topic 모드) 흐름에서는 참고도서 블록이 깔끔하게 생략되는 것도 함께 확인한다.
"""
from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.app.curriculum_blueprint import build_curriculum_blueprint
from app.modules.ChapterStudio_V1.app.curriculum_generate import (
    _build_slot_loop_prompt,
    _pdf_excerpt_block,
)
from app.modules.ChapterStudio_V1.app.generation_context import GenerationContext
from app.modules.ChapterStudio_V1.app.reference_books.retrieval import build_reference_book_context
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookPage
from app.modules.ChapterStudio_V1.pipeline import parallel_prompts as pp
from app.modules.ChapterStudio_V1.pipeline.converters import generation_input_to_initial_state
from app.modules.ChapterStudio_V1.pipeline.nodes.context_node import prepare_context_node
from app.modules.ChapterStudio_V1.pipeline.parallel_inputs import (
    build_brief,
    build_outline_text,
    build_personalization_args,
    build_reference_block,
)
from app.modules.ChapterStudio_V1.pipeline.prompt import build_generation_request


def _context(with_reference: bool) -> GenerationContext:
    reference = None
    if with_reference:
        reference = build_reference_book_context(
            [
                ReferenceBookPage(
                    page=12,
                    text="판별식은 이차방정식의 실근 개수를 판정하는 기준이며 부호에 따라 두 실근, 중근, 허근으로 나뉜다.",
                    source_title="수학의 정석",
                )
            ],
            ["판별식 실근 개수"],
            source_title="수학의 정석",
        )
        assert reference.has_hits(), "테스트 전제: 발췌 히트가 만들어져야 한다"
    return GenerationContext(
        lesson_id="lesson-1",
        tutoring_id="tutoring-1",
        user_id="user-1",
        curriculum_plan_id="plan-1",
        topic="이차방정식과 판별식",
        source_mode="pdf" if with_reference else "topic",
        pdf_file_name="수학의 정석.pdf" if with_reference else "",
        chapter_title="판별식으로 근의 개수 판정",
        chapter_brief="판별식 부호에 따른 실근 개수 판정 연습",
        reference_book_context=reference,
    )


def _component_requests(context: GenerationContext) -> dict[str, object]:
    state = generation_input_to_initial_state(context.to_generation_input())
    state.update(prepare_context_node(state))
    slide_count = context.slide_count
    template_key = str(state["template_key"])
    brief = build_brief(state)
    outline = build_outline_text(state, slide_count)
    personalization = build_personalization_args(state)
    reference_block = build_reference_block(state)
    return {
        "slides": pp.build_slides_request(
            brief, outline, slide_count, template_key, personalization, None, reference_block
        ),
        "quizzes": pp.build_quizzes_request(
            brief, outline, slide_count, template_key, personalization, reference_block
        ),
        "note": pp.build_note_request(brief, outline, slide_count, template_key, personalization, reference_block),
        "assignment": pp.build_assignment_request(
            brief, outline, slide_count, template_key, personalization, reference_block
        ),
        "voice": pp.build_voice_request(
            brief, "제목", "초점", "요약", "", 1, slide_count, personalization, reference_block
        ),
        "_single_call_state": state,
    }


def test_pdf_reference_excerpt_reaches_all_parallel_component_prompts() -> None:
    requests = _component_requests(_context(with_reference=True))
    state = requests.pop("_single_call_state")

    for name, request in requests.items():
        assert "참고도서 컨텍스트" in request.user, name
        assert "p.12" in request.user, name
        assert "위 원문 발췌에 근거해 내용을 구성" in request.user, name
        assert "일반 원리 수준만 허용" in request.user, name

    # 단일콜 경로도 같은 state에서 발췌가 프롬프트에 들어간다.
    single_call = build_generation_request(state)
    assert "p.12" in single_call.user
    assert "수학의 정석" in single_call.user


def test_topic_mode_omits_reference_block_cleanly() -> None:
    requests = _component_requests(_context(with_reference=False))
    state = requests.pop("_single_call_state")

    for name, request in requests.items():
        assert "참고도서" not in request.user, name
        assert "원문 발췌" not in request.user, name

    # 단일콜 경로는 기존 계약대로 '제공된 참고도서 없음'을 명시한다.
    single_call = build_generation_request(state)
    assert "제공된 참고도서 없음" in single_call.user


# ---------------------------------------------------------------------------
# 커리큘럼 경로 — course.source_pdf_url → 발췌 블록 → 슬롯-루프 프롬프트
# ---------------------------------------------------------------------------


def test_slot_loop_prompt_includes_pdf_excerpt_block() -> None:
    blueprint = build_curriculum_blueprint(subject="수학", lesson_count=3)

    prompt = _build_slot_loop_prompt("이차방정식", "수학", blueprint, "- p.3: 판별식 정의와 부호 해석")

    assert "참고도서 발췌(업로드 PDF의 OCR 결과" in prompt
    assert "- p.3: 판별식 정의와 부호 해석" in prompt
    assert "위 발췌 내용에 근거해 구성한다" in prompt
    assert "일반 원리 수준만 허용한다" in prompt


def test_slot_loop_prompt_omits_pdf_block_when_empty() -> None:
    blueprint = build_curriculum_blueprint(subject="수학", lesson_count=3)

    prompt = _build_slot_loop_prompt("이차방정식", "수학", blueprint)

    assert "참고도서 발췌" not in prompt
    assert "일반 원리 수준만" not in prompt


@pytest.mark.asyncio
async def test_pdf_excerpt_block_builds_page_lines_from_hybrid_search(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_hybrid_search(query: str, collection_name: str, top_k: int = 5) -> list[dict]:
        captured["query"] = query
        captured["collection"] = collection_name
        return [
            {"text": "판별식 D는 b제곱 빼기 4ac이며 부호로 실근 개수를 판정한다.", "payload": {"page_num": 7}},
            {"text": "", "payload": {"page_num": 8}},
        ]

    monkeypatch.setattr("app.modules.OCR_v1.search.hybrid_search", fake_hybrid_search)

    block = await _pdf_excerpt_block(
        {"id": "course-1", "source_pdf_url": "https://s3.example.com/books/%EC%88%98%ED%95%99%20book.pdf"},
        "이차방정식",
    )

    # OCR 인제스트와 동일한 컬렉션명 유도식(공백→언더스코어, 확장자 제거)을 쓴다.
    assert captured["collection"] == "수학_book"
    assert captured["query"] == "이차방정식"
    assert block == "- p.7: 판별식 D는 b제곱 빼기 4ac이며 부호로 실근 개수를 판정한다."


@pytest.mark.asyncio
async def test_pdf_excerpt_block_empty_without_source_pdf() -> None:
    assert await _pdf_excerpt_block({"id": "course-1", "source_pdf_url": None}, "주제") == ""
    assert await _pdf_excerpt_block({"id": "course-1"}, "주제") == ""


@pytest.mark.asyncio
async def test_pdf_excerpt_block_swallows_search_failure(monkeypatch) -> None:
    async def failing_hybrid_search(query: str, collection_name: str, top_k: int = 5) -> list[dict]:
        raise RuntimeError("Qdrant 연결 실패")

    monkeypatch.setattr("app.modules.OCR_v1.search.hybrid_search", failing_hybrid_search)

    block = await _pdf_excerpt_block({"id": "course-1", "source_pdf_url": "book.pdf"}, "주제")

    assert block == ""
