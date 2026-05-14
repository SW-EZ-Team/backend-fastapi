from __future__ import annotations

from app.modules.ChapterStudio_V1.app.reference_books.ocr_bridge import (
    reference_context_from_ocr_result,
    reference_pages_from_jsonl_lines,
    reference_pages_from_ocr_result,
)
from app.modules.ChapterStudio_V1.app.reference_books.prompt_blocks import (
    reference_assignment_step,
    reference_context_prompt,
    reference_note_bullet,
    reference_voice_sentence,
)
from app.modules.ChapterStudio_V1.app.reference_books.retrieval import build_reference_book_context
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookPage


def test_reference_pages_from_ocr_result_accepts_pipeline_pages() -> None:
    pages = reference_pages_from_ocr_result(
        {
            "pages": [
                {"page_num": 12, "text": "p-value는 귀무가설 아래에서 관측값 이상이 나올 확률이다."},
                {"page_num": 13, "text": ""},
            ]
        },
        source_title="통계 교재",
    )

    assert len(pages) == 1
    assert pages[0].page == 12
    assert pages[0].source_title == "통계 교재"


def test_reference_pages_from_ocr_result_accepts_benchmark_page_results() -> None:
    pages = reference_pages_from_ocr_result(
        {"page_results": [{"page": 5, "text_preview": "빅데이터 분석 기획과 수집 단계"}]},
    )

    assert pages[0].page == 5
    assert "수집" in pages[0].text


def test_reference_pages_from_jsonl_lines_accepts_page_text_records() -> None:
    pages = reference_pages_from_jsonl_lines(
        [
            '{"page": 3, "text": "분산 분석은 집단 평균 차이를 검정한다."}',
            '{"page": 4, "text": ""}',
            "not-json",
        ]
    )

    assert [page.page for page in pages] == [3]


def test_build_reference_book_context_selects_page_hits() -> None:
    context = build_reference_book_context(
        [
            ReferenceBookPage(page=1, text="표지와 저자 소개"),
            ReferenceBookPage(page=42, text="p-value와 신뢰구간은 통계 추론에서 함께 해석해야 한다."),
        ],
        ["p-value 신뢰구간 통계 추론"],
        source_title="통계 교재",
    )

    assert context.has_hits()
    assert context.hits[0].page == 42
    assert "p-value" in context.hits[0].snippet


def test_reference_prompt_and_output_helpers_include_page_numbers() -> None:
    context = reference_context_from_ocr_result(
        {
            "ocr_model": "paddleocr-ppv4",
            "pages": [
                {"page_num": 27, "text": "회귀분석에서 잔차는 모델이 설명하지 못한 차이를 의미한다."}
            ],
        },
        ["회귀분석 잔차 모델"],
        source_title="회귀 교재",
    )

    assert "p.27" in reference_context_prompt(context)
    assert "각 블록마다 최소 2개 bullet" in reference_context_prompt(context)
    assert "p.27" in reference_note_bullet(context)
    assert "p.27" in reference_voice_sentence(context, 0)
    assert "p.27" in reference_assignment_step(context)


def test_reference_helpers_return_empty_text_without_context() -> None:
    assert reference_context_prompt(None) == ""
    assert reference_note_bullet(None) == ""
    assert reference_voice_sentence(None, 0) == ""
    assert reference_assignment_step(None) == ""


def test_query_fallback_keeps_stopword_only_topic_searchable() -> None:
    context = build_reference_book_context(
        [ReferenceBookPage(page=7, text="학습 목표와 핵심 개념을 먼저 정리한다.")],
        ["학습 목표 핵심 개념"],
    )

    assert context.has_hits()
    assert context.hits[0].page == 7
