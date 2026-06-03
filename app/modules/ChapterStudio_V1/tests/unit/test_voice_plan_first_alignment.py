# -*- coding: utf-8 -*-
"""plan-first 음성대본 정합성·회귀 방지 테스트.

적대적 검증에서 나온 P1/P2 결함을 잡는 테스트들이다. AI 실호출 없이 순수하게 검증한다:
    - P1-1: 프롬프트가 요구하는 최상위 키 ↔ Modal guided 스키마 required 정합
    - P1-1: Modal voice 스키마가 sections·role enum을 포함하는지
    - P2-1: 슬롯 min 합 ≥ 글로벌 floor, 슬롯 max 합 ≤ 글로벌 ceiling
    - P1-1 결과: parse_voice가 sections JSON을 sections 분기로 처리(레거시 우회 안 함)
    - 무한루프 방지: apply_corrections의 voice sections=None 리셋
"""
from __future__ import annotations

import json

from app.modules.ChapterStudio_V1.common.config import (
    VOICE_SECTION_RANGES,
    voice_min_chars,
    voice_section_max_total,
    voice_section_min_total,
)
from app.modules.ChapterStudio_V1.deploy import modal_app
from app.modules.ChapterStudio_V1.pipeline.content_verify_merge import (
    apply_corrections,
    parse_correction,
)
from app.modules.ChapterStudio_V1.pipeline.parallel_prompt_text import voice_prompt
from app.modules.ChapterStudio_V1.pipeline.parallel_prompts import parse_voice
from app.modules.ChapterStudio_V1.pipeline.payload import (
    VOICE_SECTION_ROLES,
    GeneratedLessonPayload,
    parse_payload,
)

_SLIDE_COUNT = 10


# ═══════════════════════════════════════════════════════════════════
# P1-1: 프롬프트 ↔ Modal guided 스키마 정합 (이 테스트가 P1-1을 잡았어야 함)
# ═══════════════════════════════════════════════════════════════════


class TestPromptSchemaAlignment:
    """프롬프트가 요구하는 출력 구조와 Modal guided 스키마가 충돌하지 않는지 검증."""

    def test_modal_voice_schema_has_sections(self) -> None:
        """Modal voice_script_schema가 sections를 정의·강제해야 한다(P1-1 핵심)."""
        schema = modal_app.voice_script_schema(_SLIDE_COUNT)
        assert "sections" in schema["properties"], "스키마가 sections를 정의해야 한다"
        assert "sections" in schema["required"], "sections가 required여야 모델이 강제 생성"

    def test_modal_voice_schema_role_enum_matches_payload(self) -> None:
        """스키마 role enum이 payload의 VOICE_SECTION_ROLES와 정확히 일치해야 한다."""
        schema = modal_app.voice_script_schema(_SLIDE_COUNT)
        role_enum = schema["properties"]["sections"]["items"]["properties"]["role"]["enum"]
        assert role_enum == list(VOICE_SECTION_ROLES), (
            f"스키마 role enum {role_enum}이 payload roles {VOICE_SECTION_ROLES}와 다르다"
        )

    def test_modal_voice_schema_exactly_4_sections(self) -> None:
        """스키마가 정확히 4개 섹션을 강제해야 한다(plan-first 구조)."""
        schema = modal_app.voice_script_schema(_SLIDE_COUNT)
        sections = schema["properties"]["sections"]
        assert sections["minItems"] == 4
        assert sections["maxItems"] == 4

    def test_modal_voice_schema_script_text_not_required(self) -> None:
        """script_text는 sections에서 파생되므로 guided required에서 빠져야 한다.

        만약 required에 남아 있으면 모델이 sections와 script_text를 둘 다 만들어야 해서
        plan-first 파생 원칙과 충돌한다.
        """
        schema = modal_app.voice_script_schema(_SLIDE_COUNT)
        assert "script_text" not in schema["required"]

    def test_modal_mirrored_section_order_matches_config(self) -> None:
        """modal_app이 미러링한 섹션 순서가 config.VOICE_SECTION_RANGES와 정합해야 한다.

        modal_app은 deploy 독립 파일이라 값을 미러링하므로, 드리프트를 이 테스트가 막는다.
        """
        assert modal_app._VOICE_SECTION_ORDER == VOICE_SECTION_ROLES, (
            "modal_app 미러 순서가 config roles와 다르다(드리프트)"
        )
        # 미러된 maxLen 키가 config role 집합과 일치하는지.
        assert set(modal_app._VOICE_SECTION_MAXLEN.keys()) == set(VOICE_SECTION_ROLES)

    def test_prompt_top_level_keys_match_schema_required(self) -> None:
        """프롬프트가 요구하는 최상위 키 집합이 스키마 required와 정확히 일치해야 한다.

        이것이 P1-1의 본질: 프롬프트는 {slide_idx, sections}를 요구하는데 스키마가
        {slide_idx, script_text}를 강제하면 정면충돌해 plan-first가 무력화된다.
        """
        system, _user = voice_prompt(
            "brief", "title", "focus", "summary", 3,
            weak_points="", audience_level="일반", tone=50, pace=50,
            tutor_depth=50, socratic=70, learning_goal="이해", previous_title="이전",
        )
        schema = modal_app.voice_script_schema(_SLIDE_COUNT)
        schema_required = set(schema["required"])
        # 프롬프트가 명시한 최상위 키와 스키마 required가 일치.
        assert "slide_idx" in schema_required
        assert "sections" in schema_required
        # 프롬프트 system 문구가 sections 최상위 키를 명시하는지 확인.
        assert "sections" in system, "프롬프트가 sections 최상위 키를 요구해야 한다"
        assert "최상위 키는 정확히 slide_idx, sections" in system

    def test_parse_voice_routes_sections_not_legacy(self) -> None:
        """sections JSON을 받으면 parse_voice가 sections 분기로 처리해야 한다(레거시 우회 금지).

        프로덕션에서 Modal이 sections를 내면 이 경로를 타야 구조/슬롯 게이트가 작동한다.
        """
        sections_json = json.dumps({
            "slide_idx": 2,
            "sections": [
                {"role": "intro", "text": "배경을 자세히 설명합니다." + "가" * 100},
                {"role": "core", "text": "핵심 원리입니다. " + "가" * 420},
                {"role": "example", "text": "사례를 보겠습니다. " + "가" * 250},
                {"role": "closing", "text": "마무리하고 넘어갑니다." + "가" * 120},
            ],
        }, ensure_ascii=False)
        result = parse_voice(sections_json, slide_idx=2)
        assert result.sections is not None, "sections 분기를 타야 한다(레거시 폴백 아님)"
        assert len(result.sections) == 4
        # script_text가 sections에서 파생됐는지 확인(TTS 호환).
        assert "배경을 자세히 설명합니다" in result.script_text

    def test_parse_voice_legacy_script_text_still_works(self) -> None:
        """sections 없는 legacy script_text JSON도 여전히 처리돼야 한다(하위호환)."""
        legacy_json = json.dumps({
            "slide_idx": 1,
            "script_text": "가" * 950,
        }, ensure_ascii=False)
        result = parse_voice(legacy_json, slide_idx=1)
        assert result.sections is None
        assert len(result.script_text) == 950


# ═══════════════════════════════════════════════════════════════════
# P2-1: 슬롯합 vs 글로벌 floor/ceiling 정합
# ═══════════════════════════════════════════════════════════════════


class TestSlotSumGlobalAlignment:
    """슬롯 길이 합이 글로벌 게이트 범위와 정합하는지 검증."""

    def test_slot_min_sum_at_least_global_floor(self) -> None:
        """슬롯 min 합이 글로벌 floor(voice_min_chars 기본 900) 이상이어야 한다.

        그렇지 않으면 plan-first가 레거시보다 짧은 대본을 허용하는 품질 후퇴가 생긴다.
        """
        assert voice_section_min_total() >= voice_min_chars(), (
            f"슬롯 min 합 {voice_section_min_total()} < 글로벌 floor {voice_min_chars()}"
        )

    def test_slot_max_sum_at_most_1600(self) -> None:
        """슬롯 max 합이 글로벌 ceiling(1600) 이하여야 한다."""
        assert voice_section_max_total() <= 1600, (
            f"슬롯 max 합 {voice_section_max_total()} > 글로벌 ceiling 1600"
        )

    def test_all_roles_have_valid_range(self) -> None:
        """모든 role이 min < max인 유효 범위를 갖는다."""
        for role in VOICE_SECTION_ROLES:
            min_c, max_c = VOICE_SECTION_RANGES[role]
            assert 0 < min_c < max_c, f"{role} 범위 {min_c}~{max_c}가 유효하지 않다"

    def test_section_ranges_cover_all_roles(self) -> None:
        """VOICE_SECTION_RANGES가 모든 role을 빠짐없이 정의한다."""
        assert set(VOICE_SECTION_RANGES.keys()) == set(VOICE_SECTION_ROLES)


# ═══════════════════════════════════════════════════════════════════
# 무한루프 방지: apply_corrections의 sections=None 리셋
# ═══════════════════════════════════════════════════════════════════


class TestApplyCorrectionsSectionReset:
    """교정 병합 시 voice sections=None 리셋 — 무한루프 방지의 핵심."""

    def _payload_with_sections(self) -> GeneratedLessonPayload:
        """모든 voice_script에 sections를 가진 payload를 만든다."""
        voices = []
        for idx in range(_SLIDE_COUNT):
            secs = []
            for role in VOICE_SECTION_ROLES:
                min_c, _ = VOICE_SECTION_RANGES[role]
                secs.append({"role": role, "text": "가" * (min_c + 10)})
            voices.append({"slide_idx": idx, "sections": secs, "script_text": "x" * 40})
        return parse_payload(
            json.dumps({
                "slides": [_slide(i) for i in range(_SLIDE_COUNT)],
                "quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)],
                "note_blocks": [_note(i) for i in range(4)],
                "assignment": _assignment(),
                "voice_scripts": voices,
            }, ensure_ascii=False),
            _SLIDE_COUNT,
        )

    def test_corrected_voice_has_sections_reset_to_none(self) -> None:
        """교정된 voice_script는 sections가 None으로 리셋돼 script_text 정본이 된다.

        교정기는 자유 텍스트 script_text를 반환하므로, sections를 유지하면 다음 라운드에
        sections에서 파생된 옛 script_text로 다시 덮어써져 교정이 무한 반복될 수 있다.
        sections=None 리셋이 이 무한루프를 끊는다.
        """
        payload = self._payload_with_sections()
        # slide 2의 voice를 교정하는 _CorrectionResult를 만든다.
        correction_json = json.dumps({
            "slides": [],
            "quiz_explanations": [],
            "voice_scripts": [
                {"slide_idx": 2, "script_text": "교정된 새 대본입니다. " + "교" * 900}
            ],
        }, ensure_ascii=False)
        result = parse_correction(correction_json)
        merged = apply_corrections(payload, result)

        # 교정된 slide 2: sections=None, script_text는 교정값.
        voice2 = next(v for v in merged.voice_scripts if v.slide_idx == 2)
        assert voice2.sections is None, "교정된 voice의 sections는 None으로 리셋돼야 한다"
        assert "교정된 새 대본입니다" in voice2.script_text

        # 교정 안 된 slide 0: sections 보존.
        voice0 = next(v for v in merged.voice_scripts if v.slide_idx == 0)
        assert voice0.sections is not None, "교정 안 된 voice의 sections는 보존돼야 한다"

    def test_uncorrected_voice_keeps_script_text_and_sections(self) -> None:
        """교정 대상이 아닌 voice는 script_text·sections를 그대로 유지한다."""
        payload = self._payload_with_sections()
        original_voice5 = next(v for v in payload.voice_scripts if v.slide_idx == 5)
        original_text = original_voice5.script_text

        correction_json = json.dumps({
            "slides": [],
            "quiz_explanations": [],
            "voice_scripts": [
                {"slide_idx": 2, "script_text": "다른 슬라이드만 교정합니다. " + "교" * 900}
            ],
        }, ensure_ascii=False)
        result = parse_correction(correction_json)
        merged = apply_corrections(payload, result)

        voice5 = next(v for v in merged.voice_scripts if v.slide_idx == 5)
        assert voice5.script_text == original_text
        assert voice5.sections is not None


# ═══════════════════════════════════════════════════════════════════
# 전공백 sections 방어 (P2-2)
# ═══════════════════════════════════════════════════════════════════


class TestWhitespaceSectionDefense:
    """sections text가 strip 후 검증돼 전공백이 통과하지 않는지."""

    def test_whitespace_only_section_rejected(self) -> None:
        """공백 10자 text는 strip 후 0자이므로 거부돼야 한다."""
        from app.modules.ChapterStudio_V1.pipeline.payload import VoiceSection
        import pytest

        with pytest.raises(Exception):
            VoiceSection(role="intro", text="          ")  # 공백 10자

    def test_section_text_stored_stripped(self) -> None:
        """앞뒤 공백이 있는 text는 strip돼 저장된다(script_text 일관성)."""
        from app.modules.ChapterStudio_V1.pipeline.payload import VoiceSection

        sec = VoiceSection(role="core", text="   핵심 내용을 설명합니다.   ")
        assert sec.text == "핵심 내용을 설명합니다."

    def test_script_text_consistent_with_stripped_sections(self) -> None:
        """sections가 strip 저장되므로 script_text가 sections join과 정확히 일치한다."""
        from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedVoiceScript

        v = GeneratedVoiceScript(
            slide_idx=0,
            sections=[
                {"role": "intro", "text": "  배경을 자세히 설명합니다.  "},
                {"role": "core", "text": "핵심 원리입니다. " * 5},
                {"role": "example", "text": "  사례를 들겠습니다.  " * 3},
                {"role": "closing", "text": "마무리하고 다음으로 넘어갑니다."},
            ],
            script_text="dummy",
        )
        # script_text는 strip된 섹션을 공백 1개로 이은 값.
        expected = " ".join(sec.text for sec in v.sections)
        assert v.script_text == expected


# ═══════════════════════════════════════════════════════════════════
# 헬퍼
# ═══════════════════════════════════════════════════════════════════


def _slide(idx: int) -> dict:
    return {
        "slide_idx": idx,
        "title": f"슬라이드 {idx}",
        "focus": "핵심",
        "checkpoint": "점검",
        "category": "text",
        "html": "<section><p>핵심 개념을 차근차근 설명합니다.</p></section>",
        "css": "",
    }


def _quiz(idx: int) -> dict:
    return {
        "slide_idx": idx,
        "question": "질문입니다.",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "이해",
        "explanation": "정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다.",
    }


def _note(idx: int) -> dict:
    return {
        "heading": f"핵심 {idx}",
        "bullets": [
            "핵심 개념을 한 문장으로 다시 정리하면서 배경까지 복습합니다.",
            "실수하기 쉬운 경계 조건을 직접 예시로 점검합니다.",
            "오해하기 쉬운 부분을 반례와 함께 짚습니다.",
        ],
    }


def _assignment() -> dict:
    return {
        "title": "실습 과제",
        "assignment_format": "문제풀이",
        "expected_minutes": 25,
        "steps": ["개념을 적용합니다.", "결과를 정리합니다."],
        "rubric": ["근거가 명확한가", "예외 처리가 정확한가"],
    }
