"""plan-first 폴백 등록소 프로토콜.

각 파이프라인의 폴백 패스(visual_quality/render_fallback_visual,
quiz_balance_pass, voice_cohesion_pass, title_rules, ExamForge validate)를
로직 변경 없이 이름으로 참조하고 검색할 수 있는 등록소다.

사용법:
    registry = FallbackRegistry.default()
    handler = registry.get("visual_quality")
    if handler:
        result = handler(...)  # 기존 모듈 함수를 그대로 호출

등록된 어댑터는 기존 호출 경로를 건드리지 않는다. 공통 레이어가 이들을
참조할 수 있는 인덱스만 제공한다.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class FallbackRegistry:
    """슬롯 kind → 결정적 폴백 핸들러 등록소.

    얇은 래퍼로만 구성된다. 기존 모듈 함수 자체가 핸들러이며 로직 변경 없음.
    """

    def __init__(self) -> None:
        # kind(또는 패스 이름) → callable 맵
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(self, kind: str, handler: Callable[..., Any]) -> None:
        """kind에 해당하는 폴백 핸들러를 등록한다."""
        self._handlers[kind] = handler

    def get(self, kind: str) -> Callable[..., Any] | None:
        """kind에 등록된 핸들러를 반환한다. 없으면 None."""
        return self._handlers.get(kind)

    def has(self, kind: str) -> bool:
        """kind에 핸들러가 등록돼 있는지 확인한다."""
        return kind in self._handlers

    def registered_kinds(self) -> list[str]:
        """등록된 모든 kind 이름을 반환한다."""
        return list(self._handlers.keys())

    @classmethod
    def default(cls) -> "FallbackRegistry":
        """기존 파이프라인 패스가 어댑터로 등록된 기본 레지스트리를 반환한다.

        로직 변경 없이 기존 함수를 어댑터로 감싸 등록한다.
        각 어댑터는 기존 호출 경로와 완전히 독립적으로 공존한다.
        """
        registry = cls()
        # ChapterStudio 폴백 패스 등록
        _register_visual_quality(registry)
        _register_quiz_balance(registry)
        _register_voice_cohesion(registry)
        _register_title_rules(registry)
        # ExamForge 검증 패스 등록
        _register_examforge_validate(registry)
        return registry


# ── 어댑터 등록 함수 (지연 임포트로 순환 의존 방지) ───────────────────────────


def _register_visual_quality(registry: FallbackRegistry) -> None:
    """ChapterStudio visual_quality(ensure_visual_body + render_fallback_visual)."""
    try:
        from app.modules.ChapterStudio_V1.postprocess.visual_quality import ensure_visual_body
        from app.modules.ChapterStudio_V1.postprocess.visual_renderers import render_fallback_visual
        registry.register("ensure_visual_body", ensure_visual_body)
        registry.register("render_fallback_visual", render_fallback_visual)
    except ImportError:
        pass  # ChapterStudio 모듈 미설치 환경에서는 등록 생략


def _register_quiz_balance(registry: FallbackRegistry) -> None:
    """ChapterStudio quiz_balance_pass."""
    try:
        from app.modules.ChapterStudio_V1.pipeline.quiz_balance_pass import (
            apply_quiz_balance_payload,
        )
        registry.register("quiz_balance_pass", apply_quiz_balance_payload)
    except ImportError:
        pass


def _register_voice_cohesion(registry: FallbackRegistry) -> None:
    """ChapterStudio voice_cohesion_pass + voice_structure_gate."""
    try:
        from app.modules.ChapterStudio_V1.pipeline.voice_cohesion_pass import (
            apply_voice_cohesion_payload,
        )
        from app.modules.ChapterStudio_V1.pipeline.voice_structure_gate import (
            structure_gate_errors,
        )
        registry.register("voice_cohesion_pass", apply_voice_cohesion_payload)
        registry.register("voice_structure_gate", structure_gate_errors)
    except ImportError:
        pass


def _register_title_rules(registry: FallbackRegistry) -> None:
    """ChapterStudio title_rules."""
    try:
        from app.modules.ChapterStudio_V1.postprocess.title_rules import (
            is_chapter_number_title,
            relabel_chapter_title,
        )
        registry.register("title_is_chapter_number", is_chapter_number_title)
        registry.register("title_relabel", relabel_chapter_title)
    except ImportError:
        pass


def _register_examforge_validate(registry: FallbackRegistry) -> None:
    """ExamForge validate(coverage, concept_key 유일성, answer_position_plan)."""
    try:
        from app.modules.ExamForge_V1.quality.coverage_analyzer import analyze_coverage
        from app.modules.ExamForge_V1.quality.answer_positions import (
            balance_correct_answer_positions,
            answer_position_counts,
        )
        registry.register("examforge_coverage", analyze_coverage)
        registry.register("examforge_answer_positions", balance_correct_answer_positions)
        registry.register("examforge_answer_position_counts", answer_position_counts)
    except ImportError:
        pass


__all__ = ["FallbackRegistry"]
