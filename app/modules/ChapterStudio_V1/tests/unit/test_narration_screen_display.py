"""화면 표시 narration 완결성 테스트.

2차 검사에서 발견된 별개 truncation 근원 대응:
visual_renderer_utils.text()[:120]가 슬라이드 메인 내레이션 <p>에 적용되어
학습자가 보는 문장이 120자에서 중간 절단되던 버그를 막는다.

- narration_text: 메인 내레이션 전용 — 120자 cap 없이 완결 문장 보존
- text: SVG 라벨 전용 — 120자 cap 유지하되 단어 중간 노출 대신 말줄임표(…)
- render_visual_slide: <p> 메인 내레이션이 _narration_text를 쓰는지 검증
"""
from __future__ import annotations

import re
from html import unescape

import pytest

from app.modules.ChapterStudio_V1.postprocess.visual_renderer_utils import (
    narration_text,
    text,
)
from app.modules.ChapterStudio_V1.postprocess.visual_renderers import render_visual_slide


def _extract_paragraph(html: str) -> str:
    """슬라이드 HTML header의 <p> 메인 내레이션 텍스트를 unescape해 꺼낸다."""
    match = re.search(r"<p>(.*?)</p>", html, re.DOTALL)
    assert match is not None, f"HTML에 <p> 내레이션이 없다: {html[:200]}"
    return unescape(match.group(1))


def _is_complete(text_value: str) -> bool:
    """화면 표시 문장이 완결로 끝나는지 판별한다(부호 또는 한국어 종결 어미)."""
    stripped = text_value.strip()
    if not stripped:
        return False
    if stripped[-1] in ".!?。！？":
        return True
    last_word = stripped.rsplit(" ", 1)[-1] if " " in stripped else stripped
    endings = ("습니다", "합니다", "입니다", "됩니다", "해요", "예요", "이에요", "어요", "아요")
    return any(last_word.endswith(e) for e in endings)


# ---------------------------------------------------------------------------
# narration_text 단위 테스트 (메인 내레이션 전용)
# ---------------------------------------------------------------------------


class TestNarrationText:
    """메인 내레이션 전용 helper는 120자 cap을 적용하지 않는다."""

    def test_short_narration_preserved(self) -> None:
        narration = "이차방정식은 ax²+bx+c=0 형태입니다."
        assert unescape(narration_text(narration, "기본")) == narration

    def test_long_complete_narration_not_truncated_at_120(self) -> None:
        """120자 초과 완결 narration이 절단 없이 전체 보존된다(구버전 버그 회귀 방어)."""
        narration = (
            "이차방정식의 판별식은 D=b²-4ac로 정의되며 근의 개수와 종류를 미리 알려주는 핵심 도구입니다. "
            "D가 0보다 크면 서로 다른 두 실근을 가지고, D가 정확히 0이면 중근이라 부르는 하나의 실근을 가지며, "
            "D가 0보다 작으면 실근이 없고 두 허근을 가집니다. 따라서 방정식을 직접 풀지 않고도 판별식만 계산하면 "
            "해의 성질을 빠르게 파악할 수 있습니다."
        )
        assert len(narration) > 120
        result = unescape(narration_text(narration, "기본"))
        assert result == narration, "120자 초과 narration이 절단됨"
        assert _is_complete(result)

    def test_narration_around_360_chars_preserved(self) -> None:
        """프롬프트 지시 상한(360자) 부근 narration도 그대로 표시된다."""
        sentence = "이차방정식의 근을 구하는 방법에는 인수분해와 완전제곱식과 근의 공식 세 가지가 있습니다. "
        narration = (sentence * 8).strip()
        assert 300 < len(narration) < 600
        result = unescape(narration_text(narration, "기본"))
        assert result == narration

    def test_empty_uses_default(self) -> None:
        assert unescape(narration_text("", "기본 내레이션입니다.")) == "기본 내레이션입니다."

    def test_pathological_long_input_trimmed_at_sentence_boundary(self) -> None:
        """비정상적으로 긴 입력(1200자 초과)은 완결 문장 경계에서만 잘린다."""
        narration = "이것은 하나의 완결 문장입니다. " * 100  # 약 1700자
        result = unescape(narration_text(narration, "기본"))
        # 안전 상한 적용되더라도 문장 중간 절단이 아니어야 함
        assert _is_complete(result), f"안전 절단 후 불완결: ...{result[-20:]!r}"
        assert result.rstrip().endswith(".")

    def test_html_escaped(self) -> None:
        result = narration_text("a < b 이고 c > d 입니다.", "기본")
        assert "&lt;" in result and "&gt;" in result


# ---------------------------------------------------------------------------
# text 단위 테스트 (SVG 라벨 전용 — cap 유지 + 말줄임표)
# ---------------------------------------------------------------------------


class TestLabelText:
    """SVG 라벨용 helper는 120자 cap을 유지하되 말줄임표로 절단을 드러낸다."""

    def test_short_label_preserved(self) -> None:
        assert unescape(text("영하 5", "기본")) == "영하 5"

    def test_long_label_capped_with_ellipsis(self) -> None:
        long_label = "가" * 200
        result = unescape(text(long_label, "기본"))
        assert len(result) <= 120
        assert result.endswith("…"), "긴 라벨이 말줄임표 없이 단어 중간 노출됨"

    def test_label_exactly_120_not_capped(self) -> None:
        label = "나" * 120
        result = unescape(text(label, "기본"))
        assert result == label
        assert "…" not in result

    def test_empty_label_uses_default(self) -> None:
        assert unescape(text("", "기본 라벨")) == "기본 라벨"


# ---------------------------------------------------------------------------
# render_visual_slide 통합 테스트 (화면 표시 경로)
# ---------------------------------------------------------------------------


class TestRenderVisualSlideNarration:
    """render_visual_slide가 메인 내레이션을 120자 cap 없이 완결로 표시한다."""

    _STEP_DATA = {"steps": [{"label": "1단계", "detail": "조건 확인", "result": "정리"}]}

    def test_long_narration_fully_displayed(self) -> None:
        """220자 완결 narration이 화면 <p>에 그대로 표시된다(120자 절단 0)."""
        narration = (
            "이차방정식의 판별식은 D=b²-4ac로 정의되며 근의 개수와 종류를 미리 알려주는 핵심 도구입니다. "
            "D가 0보다 크면 서로 다른 두 실근을 가지고, D가 정확히 0이면 중근이라 부르는 하나의 실근을 가지며, "
            "D가 0보다 작으면 실근이 없고 두 허근을 가집니다. 따라서 판별식만 계산하면 해의 성질을 파악할 수 있습니다."
        )
        assert len(narration) > 120
        html = render_visual_slide("판별식의 의미", narration, "step_flow", self._STEP_DATA)
        displayed = _extract_paragraph(html)
        assert displayed == narration, (
            f"화면 narration이 절단됨: {len(displayed)}자, ...{displayed[-20:]!r}"
        )
        assert _is_complete(displayed)

    def test_displayed_narration_not_cut_at_120(self) -> None:
        """화면 표시 narration 길이가 정확히 120자(=구버전 cap)에 묶이지 않는다."""
        narration = "이차방정식을 푸는 세 가지 방법을 차례대로 살펴봅니다. " * 4
        narration = narration.strip()
        html = render_visual_slide("풀이 방법", narration, "step_flow", self._STEP_DATA)
        displayed = _extract_paragraph(html)
        # 구버전이라면 정확히 120자였을 것 — 이제 전체가 표시되어야 함
        assert len(displayed) != 120 or len(narration) == 120
        assert _is_complete(displayed)

    @pytest.mark.parametrize(
        "narration",
        [
            "이차방정식의 근은 방정식을 참으로 만드는 x값이며, 인수분해와 근의 공식으로 구할 수 있고, "
            "판별식으로 근의 개수를 미리 알 수 있어서 풀이의 방향을 빠르게 정할 수 있습니다.",
            "수직선에서 오른쪽에 있는 수가 더 큰 수이므로 음수를 비교할 때는 절댓값이 아니라 "
            "수직선 위치를 기준으로 판단해야 정확한 대소 관계를 알 수 있습니다.",
        ],
    )
    def test_realistic_narrations_complete_on_screen(self, narration: str) -> None:
        """프롬프트 범위 narration들이 화면에서 완결 문장으로 표시된다."""
        html = render_visual_slide("핵심 개념", narration, "example_box", {
            "problem": "예제",
            "steps": ["풀이"],
            "answer": "정답",
        })
        displayed = _extract_paragraph(html)
        assert displayed == narration
        assert _is_complete(displayed)

    def test_title_still_uses_short_label_cap(self) -> None:
        """제목은 여전히 라벨용 cap(120자)을 적용받는다(회귀 방어)."""
        long_title = "가" * 200
        html = render_visual_slide(long_title, "완결 내레이션입니다.", "step_flow", self._STEP_DATA)
        match = re.search(r"<h2>(.*?)</h2>", html)
        assert match is not None
        title_text = unescape(match.group(1))
        assert len(title_text) <= 120
