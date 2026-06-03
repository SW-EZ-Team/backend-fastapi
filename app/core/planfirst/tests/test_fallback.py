"""FallbackRegistry 단위 테스트.

기존 패스들의 등록·조회·로직 무변경을 확인한다.
"""
from __future__ import annotations

import pytest

from app.core.planfirst.fallback import FallbackRegistry


class TestFallbackRegistryBasic:
    def test_empty_registry(self) -> None:
        reg = FallbackRegistry()
        assert reg.registered_kinds() == []
        assert reg.get("anything") is None
        assert not reg.has("anything")

    def test_register_and_get(self) -> None:
        reg = FallbackRegistry()

        def handler(x: int) -> int:
            """등록·조회용 더미 핸들러."""
            return x * 2

        reg.register("double", handler)
        assert reg.get("double") is handler
        assert reg.has("double")

    def test_registered_kinds_returns_all(self) -> None:
        reg = FallbackRegistry()
        reg.register("a", lambda: None)
        reg.register("b", lambda: None)
        assert set(reg.registered_kinds()) == {"a", "b"}

    def test_get_missing_returns_none(self) -> None:
        reg = FallbackRegistry()
        reg.register("existing", lambda: None)
        assert reg.get("nonexistent") is None


class TestDefaultRegistry:
    """FallbackRegistry.default()에 등록된 어댑터를 확인한다."""

    def setup_method(self) -> None:
        self.reg = FallbackRegistry.default()

    def test_ensure_visual_body_registered(self) -> None:
        handler = self.reg.get("ensure_visual_body")
        assert handler is not None
        assert callable(handler)

    def test_render_fallback_visual_registered(self) -> None:
        handler = self.reg.get("render_fallback_visual")
        assert handler is not None
        assert callable(handler)

    def test_quiz_balance_pass_registered(self) -> None:
        handler = self.reg.get("quiz_balance_pass")
        assert handler is not None
        assert callable(handler)

    def test_voice_cohesion_pass_registered(self) -> None:
        handler = self.reg.get("voice_cohesion_pass")
        assert handler is not None
        assert callable(handler)

    def test_voice_structure_gate_registered(self) -> None:
        handler = self.reg.get("voice_structure_gate")
        assert handler is not None
        assert callable(handler)

    def test_title_relabel_registered(self) -> None:
        handler = self.reg.get("title_relabel")
        assert handler is not None
        assert callable(handler)

    def test_examforge_coverage_registered(self) -> None:
        handler = self.reg.get("examforge_coverage")
        assert handler is not None
        assert callable(handler)

    def test_examforge_answer_positions_registered(self) -> None:
        handler = self.reg.get("examforge_answer_positions")
        assert handler is not None
        assert callable(handler)


class TestDefaultRegistryAdapterBehavior:
    """등록된 어댑터가 기존 모듈 함수를 그대로 호출하는지 확인한다."""

    def setup_method(self) -> None:
        self.reg = FallbackRegistry.default()

    def test_render_fallback_visual_produces_html(self) -> None:
        """render_fallback_visual 어댑터가 HTML 문자열을 반환하는지 확인."""
        render = self.reg.get("render_fallback_visual")
        assert render is not None
        result = render("테스트 제목", "테스트 내레이션입니다.")
        assert isinstance(result, str)
        # 기존 render_fallback_visual은 HTML 마크업을 반환한다
        assert len(result) > 0

    def test_title_is_chapter_number_adapter(self) -> None:
        """title_is_chapter_number 어댑터가 원본 함수와 동일하게 동작하는지 확인."""
        from app.modules.ChapterStudio_V1.postprocess.title_rules import (
            is_chapter_number_title,
        )
        is_chapter = self.reg.get("title_is_chapter_number")
        assert is_chapter is not None
        # 로직 무변경 확인: 같은 입력 → 같은 출력
        assert is_chapter("수직선과 정수의 위치 3") == is_chapter_number_title("수직선과 정수의 위치 3")
        assert is_chapter("음수끼리의 크기 비교") == is_chapter_number_title("음수끼리의 크기 비교")

    def test_examforge_answer_position_counts_adapter(self) -> None:
        """examforge_answer_position_counts 어댑터가 원본 함수와 동일하게 동작하는지 확인."""
        from app.modules.ExamForge_V1.quality.answer_positions import answer_position_counts
        adapter = self.reg.get("examforge_answer_position_counts")
        assert adapter is not None
        questions = [
            {"options": [{"label": "1", "is_correct": True}, {"label": "2", "is_correct": False}]},
            {"options": [{"label": "1", "is_correct": False}, {"label": "2", "is_correct": True}]},
        ]
        assert adapter(questions) == answer_position_counts(questions)
