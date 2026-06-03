from __future__ import annotations

from app.modules.ChapterStudio_V1.db.title_fallback import extract_heading_title, meaningful_slide_title


def test_extract_heading_title_reads_escaped_iframe_srcdoc_h2() -> None:
    html = (
        '<iframe sandbox="allow-scripts" '
        'srcdoc="&lt;!DOCTYPE html&gt;&lt;html&gt;&lt;body&gt;'
        '&lt;h2&gt;정수 개념의 전체 구조 파악&lt;/h2&gt;'
        '&lt;/body&gt;&lt;/html&gt;"></iframe>'
    )

    assert extract_heading_title(html) == "정수 개념의 전체 구조 파악"


def test_extract_heading_title_reads_plain_h2_with_attributes() -> None:
    html = '<section><h2 class="x">자연수의 한계와 음수의 필요성</h2></section>'

    assert extract_heading_title(html) == "자연수의 한계와 음수의 필요성"


def test_heading_missing_falls_back_to_voice_phrase() -> None:
    html = '<iframe srcdoc="&lt;section&gt;&lt;p&gt;본문 설명입니다.&lt;/p&gt;&lt;/section&gt;"></iframe>'
    title = meaningful_slide_title(
        "정수의 세계 1",
        "정수의 세계",
        0,
        html,
        "음수는 기준점보다 작은 위치를 나타냅니다.",
    )

    assert extract_heading_title(html) == ""
    assert title.startswith("음수 기준점보다")


def test_meaningful_slide_title_prefers_heading_over_voice_phrase() -> None:
    html = (
        '<iframe sandbox="allow-scripts" '
        'srcdoc="&lt;section&gt;&lt;h2&gt;정수 개념의 전체 구조 파악&lt;/h2&gt;&lt;/section&gt;">'
        "</iframe>"
    )
    title = meaningful_slide_title(
        "정수의 세계 2",
        "정수의 세계",
        1,
        "살펴본 수직선 기억나죠. 음수 위치를 다시 봅니다.",
        html,
    )

    assert title == "정수 개념의 전체 구조 파악"


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


# ── P1: CSS 누출 방어 (title 필드에 CSS 텍스트가 유입되는 경우) ────────────────


def test_meaningful_slide_title_rejects_css_root_color_scheme() -> None:
    """P1 픽스: AI 모델이 title='root color-scheme light'를 반환하면 제목으로 쓰지 않는다."""
    title = meaningful_slide_title(
        "root color-scheme light",
        "Python 기초",
        1,
        "파이썬 기초 개념을 설명합니다.",
    )

    assert "root" not in title
    assert "color-scheme" not in title


def test_meaningful_slide_title_rejects_css_brace_pattern() -> None:
    """:root{...} 형태의 CSS가 title 필드에 들어오면 폴백 소스에서 제목을 추출한다."""
    title = meaningful_slide_title(
        ":root{color-scheme:light dark}",
        "정렬 알고리즘",
        0,
        "이진 탐색은 정렬된 배열에서 빠르게 원소를 찾습니다.",
    )

    assert ":root" not in title
    assert "color-scheme" not in title


def test_meaningful_slide_title_rejects_pure_ascii_no_meaning() -> None:
    """한국어/숫자 없는 순수 영문 CSS 토큰은 제목으로 허용되지 않는다."""
    title = meaningful_slide_title(
        "color scheme light",
        "수학 기초",
        2,
        "음수끼리 크기 비교는 절댓값이 작을수록 큽니다.",
    )

    # 의미 있는 한국어 fallback으로 대체돼야 한다
    assert "color" not in title
    assert "scheme" not in title
