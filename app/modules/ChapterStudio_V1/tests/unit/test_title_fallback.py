from __future__ import annotations

from app.modules.ChapterStudio_V1.db.title_fallback import meaningful_slide_title


def test_meaningful_slide_title_replaces_chapter_number_placeholder() -> None:
    title = meaningful_slide_title(
        "정수의 세계 3",
        "정수의 세계",
        2,
        "음수는 수직선 왼쪽 위치를 나타냅니다. 기준점 0과 함께 비교합니다.",
    )

    assert title == "음수 수직선 왼쪽 위치"


def test_meaningful_slide_title_keeps_specific_llm_title() -> None:
    title = meaningful_slide_title("음수끼리의 크기 비교", "정수의 세계", 2, "음수 비교 설명입니다.")

    assert title == "음수끼리의 크기 비교"


def test_meaningful_slide_title_uses_final_fallback_when_sources_are_empty() -> None:
    title = meaningful_slide_title("", "정수의 세계", 2, "", "   ")

    assert title == "정수의 세계 3"


def test_meaningful_slide_title_skips_empty_intro_sentence() -> None:
    title = meaningful_slide_title(
        "정수의 세계 12",
        "정수의 세계",
        11,
        "안녕하세요. 음수는 기준점보다 작은 위치를 나타내고, 절댓값은 0과의 거리입니다.",
    )

    assert title.startswith("음수 기준점보다 위치")
    assert title != "정수의 세계 12"


def test_meaningful_slide_title_strips_repeated_conversational_intro() -> None:
    title = meaningful_slide_title(
        "",
        "정수의 세계",
        0,
        "튜터야! 오늘은 먼저 정수의 덧셈을 수직선으로 살펴봅시다.",
    )

    assert title.startswith("정수 덧셈")
    assert "튜터야" not in title
    assert "오늘" not in title
