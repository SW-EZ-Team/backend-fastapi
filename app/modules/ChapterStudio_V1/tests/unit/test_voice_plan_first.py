"""plan-first 음성대본 생성 리팩터 신규 단위 테스트.

AI 실호출 없이 순수 함수/스키마만 검증한다. 다음 항목을 다룬다:
    A. 스키마 — sections 4개 강제, role 완전집합·순서, script_text join 파생, 레거시 폴백
    B. 블루프린트 — slide_idx별 intro_mode 결정, 섹션 슬롯 수·role·길이 범위
    C. 구조 게이트 — 3개/5개/role 누락/순서 뒤바뀜/intro 모드 오류 검출
    D. 섹션 길이 게이트 — 슬롯별 미달 location 정확, 레거시 경로 하위호환
    E. voice_cohesion — 도입 중복 슬롯만 재작성, 타 슬롯 불변
"""
from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.common.config import VOICE_SECTION_RANGES
from app.modules.ChapterStudio_V1.pipeline.parallel_inputs import (
    VoiceBlueprint,
    build_voice_blueprint,
)
from app.modules.ChapterStudio_V1.pipeline.payload import (
    VOICE_SECTION_ROLES,
    GeneratedVoiceScript,
    VoiceSection,
    parse_payload,
)
from app.modules.ChapterStudio_V1.pipeline.voice_length_gate import (
    length_gate_errors,
    short_voice_indices,
    voice_extend_user_prompt,
)
from app.modules.ChapterStudio_V1.pipeline.voice_structure_gate import structure_gate_errors

_SLIDE_COUNT = 10


# ═══════════════════════════════════════════════════════════════════
# A. 스키마 검증
# ═══════════════════════════════════════════════════════════════════


class TestSchemaA:
    """GeneratedVoiceScript 스키마 계약."""

    def _make_sections(self, roles: list[str] | None = None) -> list[dict]:
        roles = roles or list(VOICE_SECTION_ROLES)
        texts = {
            "intro": "이 개념이 중요한 이유는 다음과 같습니다. 기초부터 설명합니다.",
            "core": ("핵심 원리를 설명합니다. " * 25),
            "example": ("구체적 예시를 들겠습니다. " * 15),
            "closing": "다음 화면으로 이어집니다. 이 내용을 꼭 기억하세요.",
        }
        return [{"role": r, "text": texts.get(r, "텍스트 내용입니다. " * 5)} for r in roles]

    def test_sections_4_required_valid(self) -> None:
        """정확히 4개 sections가 있으면 파싱 성공."""
        v = GeneratedVoiceScript(slide_idx=0, sections=self._make_sections(), script_text="dummy")
        assert v.sections is not None
        assert len(v.sections) == 4
        for sec, expected_role in zip(v.sections, VOICE_SECTION_ROLES):
            assert sec.role == expected_role

    def test_script_text_derived_from_sections(self) -> None:
        """sections가 있으면 script_text는 sections join 파생값이다(TTS 호환)."""
        sections = self._make_sections()
        v = GeneratedVoiceScript(slide_idx=2, sections=sections, script_text="should_be_overwritten")
        # intro text가 script_text에 반드시 포함돼야 한다.
        intro_text = sections[0]["text"]
        assert intro_text[:10] in v.script_text
        # 모든 섹션 내용이 script_text에 들어가야 한다.
        for sec in sections:
            assert sec["text"][:8] in v.script_text

    def test_legacy_script_text_only_passes(self) -> None:
        """sections 없이 script_text만 오는 레거시 입력도 파싱 가능(하위호환)."""
        v = GeneratedVoiceScript(slide_idx=3, script_text="가" * 100)
        assert v.sections is None
        assert len(v.script_text) == 100

    def test_legacy_min_length_40_enforced(self) -> None:
        """레거시 경로에서 script_text min_length=40 하한은 유지된다."""
        with pytest.raises(Exception):
            GeneratedVoiceScript(slide_idx=0, script_text="짧음")

    def test_script_text_always_valid_string_for_tts(self) -> None:
        """sections 유무와 무관하게 script_text는 항상 유효한 문자열이다."""
        # sections 있는 경우
        v_with = GeneratedVoiceScript(slide_idx=0, sections=self._make_sections(), script_text="x" * 40)
        assert isinstance(v_with.script_text, str) and len(v_with.script_text) >= 40
        # sections 없는 경우
        v_without = GeneratedVoiceScript(slide_idx=0, script_text="가" * 100)
        assert isinstance(v_without.script_text, str) and len(v_without.script_text) >= 40


# ═══════════════════════════════════════════════════════════════════
# B. 블루프린트 — intro_mode 결정, 섹션 슬롯 메타
# ═══════════════════════════════════════════════════════════════════


class TestBlueprintB:
    """VoiceBlueprint 결정론적 속성."""

    def test_slide_idx_0_is_greeting(self) -> None:
        """slide_idx==0은 greeting 모드여야 한다."""
        bp = build_voice_blueprint(0, "")
        assert bp.intro_mode == "greeting"

    def test_slide_idx_nonzero_is_bridge(self) -> None:
        """slide_idx>0은 bridge 모드여야 한다(previous_title 유무 무관)."""
        for idx in (1, 5, 9):
            bp = build_voice_blueprint(idx, "직전 슬라이드")
            assert bp.intro_mode == "bridge", f"slide_idx={idx} should be bridge"

    def test_blueprint_always_4_sections(self) -> None:
        """블루프린트 섹션 수는 항상 4개 고정이다."""
        for idx in range(5):
            bp = build_voice_blueprint(idx, "")
            assert len(bp.sections) == 4

    def test_blueprint_roles_ordered(self) -> None:
        """블루프린트 섹션 role 순서는 VOICE_SECTION_ROLES와 일치한다."""
        bp = build_voice_blueprint(3, "직전")
        actual_roles = tuple(sec.role for sec in bp.sections)
        assert actual_roles == VOICE_SECTION_ROLES

    def test_blueprint_length_ranges_match_config(self) -> None:
        """블루프린트 섹션 길이 범위는 VOICE_SECTION_RANGES 상수와 일치한다."""
        bp = build_voice_blueprint(2, "")
        for sec in bp.sections:
            expected_min, expected_max = VOICE_SECTION_RANGES[sec.role]
            assert sec.min_chars == expected_min
            assert sec.max_chars == expected_max

    def test_intro_section_has_mode(self) -> None:
        """intro 슬롯에만 intro_mode가 설정된다."""
        bp = build_voice_blueprint(0, "")
        intro_sec = next(s for s in bp.sections if s.role == "intro")
        others = [s for s in bp.sections if s.role != "intro"]
        assert intro_sec.intro_mode is not None
        for sec in others:
            assert sec.intro_mode is None


# ═══════════════════════════════════════════════════════════════════
# C. 구조 게이트
# ═══════════════════════════════════════════════════════════════════


class TestStructureGateC:
    """structure_gate_errors 순수 함수 검증."""

    def _good_sections(self) -> list[dict]:
        return [
            {"role": "intro", "text": "이 개념의 배경입니다. 왜 중요한지 설명합니다."},
            {"role": "core", "text": "핵심 원리입니다. " * 25},
            {"role": "example", "text": "사례입니다. " * 20},
            {"role": "closing", "text": "마무리입니다. 다음 화면으로 넘어갑니다."},
        ]

    def _payload_with_sections(self, sections_list: list[list[dict]], greeting_at: int | None = None):
        """각 슬라이드에 sections를 주입한 payload를 만든다."""
        voices = []
        for idx in range(_SLIDE_COUNT):
            secs = sections_list[idx] if idx < len(sections_list) else self._good_sections()
            if greeting_at is not None and idx == greeting_at:
                # 인사말로 시작하는 intro text를 주입한다.
                secs = [
                    {"role": "intro", "text": "안녕하세요. 이번 시간에는 핵심을 배웁니다."},
                    *secs[1:],
                ]
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

    def test_valid_sections_no_errors(self) -> None:
        """4개 role 완전집합, 올바른 순서 → 오류 없음."""
        sections_list = [self._good_sections() for _ in range(_SLIDE_COUNT)]
        payload = self._payload_with_sections(sections_list)
        errors = structure_gate_errors(payload)
        assert errors == []

    def test_3_sections_flagged_via_direct_injection(self) -> None:
        """섹션 3개이면 구조 게이트 오류 발생 — parse_payload를 우회해 직접 주입."""
        from app.modules.ChapterStudio_V1.pipeline.payload import (
            GeneratedLessonPayload,
            GeneratedVoiceScript,
            VoiceSection,
        )
        # Pydantic 스키마를 우회해 직접 VoiceScript를 만들기 위해 model_construct를 사용한다.
        # 한국어 문자 하나=1자이므로 10자 이상 문자열을 사용한다.
        bad_sections = [
            VoiceSection(role="intro", text="배경을 자세히 설명합니다."),
            VoiceSection(role="core", text="핵심 설명입니다. " * 25),
            VoiceSection(role="example", text="예시를 들겠습니다. " * 15),
            # closing 없음 → 3개
        ]
        script_bad = GeneratedVoiceScript.model_construct(
            slide_idx=0,
            script_text="텍스트" * 20,
            sections=bad_sections,
        )
        good_sections = [
            VoiceSection(role="intro", text="배경을 자세히 설명합니다."),
            VoiceSection(role="core", text="핵심 설명입니다. " * 25),
            VoiceSection(role="example", text="예시를 들겠습니다. " * 15),
            VoiceSection(role="closing", text="마무리하고 다음으로 넘어갑니다."),
        ]
        scripts = [script_bad] + [
            GeneratedVoiceScript.model_construct(
                slide_idx=idx,
                script_text="텍스트" * 20,
                sections=good_sections,
            )
            for idx in range(1, _SLIDE_COUNT)
        ]
        from app.modules.ChapterStudio_V1.pipeline.payload import (
            GeneratedAssignment,
            GeneratedNoteBlock,
            GeneratedQuiz,
            GeneratedSlide,
        )
        payload = GeneratedLessonPayload.model_construct(
            slides=[GeneratedSlide.model_construct(
                slide_idx=i, title=f"슬라이드 {i}", focus="핵심", checkpoint="점검",
                category="text", html="<section><p>내용</p></section>", css="",
                narration="", visual={},
            ) for i in range(_SLIDE_COUNT)],
            quizzes=[GeneratedQuiz.model_construct(
                slide_idx=i, question="질문", choices=["A", "B", "C", "D"],
                answer_idx=0, difficulty="이해",
                explanation="정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다.",
            ) for i in range(_SLIDE_COUNT)],
            note_blocks=[GeneratedNoteBlock.model_construct(
                heading=f"핵심 {i}",
                bullets=["복습", "점검", "확인"],
            ) for i in range(4)],
            assignment=GeneratedAssignment.model_construct(
                title="과제", assignment_format="풀이", expected_minutes=25,
                steps=["적용"], rubric=["근거"],
            ),
            voice_scripts=scripts,
        )
        errors = structure_gate_errors(payload)
        slide0_errors = [e for e in errors if e["slide_idx"] == 0]
        assert slide0_errors, "3개 섹션은 구조 게이트에 걸려야 한다"

    def test_wrong_order_flagged_via_direct_injection(self) -> None:
        """섹션 순서가 뒤바뀌면 구조 게이트 오류 발생 — model_construct로 직접 주입."""
        from app.modules.ChapterStudio_V1.pipeline.payload import (
            GeneratedAssignment,
            GeneratedLessonPayload,
            GeneratedNoteBlock,
            GeneratedQuiz,
            GeneratedSlide,
            GeneratedVoiceScript,
            VoiceSection,
        )
        # core → intro 순서로 뒤바뀐 sections (한국어 10자 이상 확인)
        bad_sections = [
            VoiceSection(role="core", text="핵심 설명입니다. " * 25),
            VoiceSection(role="intro", text="배경을 자세히 설명합니다."),
            VoiceSection(role="example", text="예시를 들겠습니다. " * 15),
            VoiceSection(role="closing", text="마무리하고 다음으로 넘어갑니다."),
        ]
        script_bad = GeneratedVoiceScript.model_construct(
            slide_idx=0, script_text="텍스트" * 20, sections=bad_sections,
        )
        good_sections = [
            VoiceSection(role="intro", text="배경을 자세히 설명합니다."),
            VoiceSection(role="core", text="핵심 설명입니다. " * 25),
            VoiceSection(role="example", text="예시를 들겠습니다. " * 15),
            VoiceSection(role="closing", text="마무리하고 다음으로 넘어갑니다."),
        ]
        scripts = [script_bad] + [
            GeneratedVoiceScript.model_construct(
                slide_idx=idx, script_text="텍스트" * 20, sections=good_sections,
            )
            for idx in range(1, _SLIDE_COUNT)
        ]
        payload = GeneratedLessonPayload.model_construct(
            slides=[GeneratedSlide.model_construct(
                slide_idx=i, title=f"슬라이드 {i}", focus="핵심", checkpoint="점검",
                category="text", html="<section><p>내용</p></section>", css="",
                narration="", visual={},
            ) for i in range(_SLIDE_COUNT)],
            quizzes=[GeneratedQuiz.model_construct(
                slide_idx=i, question="질문", choices=["A", "B", "C", "D"],
                answer_idx=0, difficulty="이해",
                explanation="정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다.",
            ) for i in range(_SLIDE_COUNT)],
            note_blocks=[GeneratedNoteBlock.model_construct(
                heading=f"핵심 {i}", bullets=["복습", "점검", "확인"],
            ) for i in range(4)],
            assignment=GeneratedAssignment.model_construct(
                title="과제", assignment_format="풀이", expected_minutes=25,
                steps=["적용"], rubric=["근거"],
            ),
            voice_scripts=scripts,
        )
        errors = structure_gate_errors(payload)
        slide0_errors = [e for e in errors if e["slide_idx"] == 0]
        assert slide0_errors, "잘못된 순서는 구조 게이트에 걸려야 한다"

    def test_greeting_on_slide0_allowed(self) -> None:
        """slide_idx==0에서 인사말로 시작해도 오류 없음(greeting 모드 허용)."""
        sections_list = [self._good_sections() for _ in range(_SLIDE_COUNT)]
        # slide 0에 인사말 주입
        sections_list[0] = [
            {"role": "intro", "text": "안녕하세요. 이번 시간에는 정수를 배웁니다."},
            *self._good_sections()[1:],
        ]
        payload = self._payload_with_sections(sections_list)
        errors = structure_gate_errors(payload)
        slide0_errors = [e for e in errors if e["slide_idx"] == 0]
        # slide 0에서 인사말은 허용이므로 intro_mode 오류가 없어야 한다.
        intro_mode_errors = [e for e in slide0_errors if "intro_mode" in str(e.get("location", ""))]
        assert intro_mode_errors == [], f"slide_idx=0 인사말은 허용이다: {intro_mode_errors}"

    def test_greeting_on_nonzero_slide_flagged(self) -> None:
        """slide_idx>0에서 인사말로 시작하면 intro_mode 오류 발생."""
        sections_list = [self._good_sections() for _ in range(_SLIDE_COUNT)]
        # slide 3에 인사말 주입
        sections_list[3] = [
            {"role": "intro", "text": "안녕하세요. 이번 화면에서는 다음을 다룹니다."},
            *self._good_sections()[1:],
        ]
        payload = self._payload_with_sections(sections_list)
        errors = structure_gate_errors(payload)
        slide3_errors = [e for e in errors if e["slide_idx"] == 3]
        assert slide3_errors, "slide_idx>0 인사말은 구조 게이트에 걸려야 한다"

    def test_legacy_no_sections_skipped(self) -> None:
        """sections 없는 레거시 voice_script는 구조 게이트 미적용(no-op)."""
        payload = parse_payload(
            json.dumps({
                "slides": [_slide(i) for i in range(_SLIDE_COUNT)],
                "quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)],
                "note_blocks": [_note(i) for i in range(4)],
                "assignment": _assignment(),
                "voice_scripts": [
                    {"slide_idx": i, "script_text": "가" * 950}
                    for i in range(_SLIDE_COUNT)
                ],
            }, ensure_ascii=False),
            _SLIDE_COUNT,
        )
        errors = structure_gate_errors(payload)
        assert errors == [], "레거시 경로는 구조 게이트를 통과해야 한다"


# ═══════════════════════════════════════════════════════════════════
# D. 섹션 길이 게이트
# ═══════════════════════════════════════════════════════════════════


class TestSectionLengthGateD:
    """length_gate_errors — 슬롯별 길이 검증."""

    def _payload_sections_custom_lengths(
        self, role_overrides: dict[str, int], slide_idx: int = 0
    ):
        """지정 슬라이드에만 role별 길이를 오버라이드해 payload를 만든다."""
        voices = []
        for idx in range(_SLIDE_COUNT):
            if idx == slide_idx:
                secs = []
                for role in VOICE_SECTION_ROLES:
                    min_c, _ = VOICE_SECTION_RANGES[role]
                    # 오버라이드가 있으면 그 길이, 없으면 min_c+10으로 합격.
                    char_count = role_overrides.get(role, min_c + 10)
                    secs.append({"role": role, "text": "가" * char_count})
                voices.append({"slide_idx": idx, "sections": secs, "script_text": "x" * 40})
            else:
                # 다른 슬라이드는 모두 합격 길이.
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

    def test_all_slots_pass_no_errors(self) -> None:
        """모든 슬롯이 범위 내이면 오류 없음."""
        payload = self._payload_sections_custom_lengths({})
        errors = length_gate_errors(payload, 900)
        assert errors == []

    def test_intro_slot_short_flagged_with_correct_location(self) -> None:
        """intro 슬롯이 미달이면 location에 role이 포함된다.

        intro min_chars=80, schema min_length=10 이므로 15자를 사용한다(schema OK, gate 미달).
        """
        payload = self._payload_sections_custom_lengths({"intro": 15}, slide_idx=2)
        errors = length_gate_errors(payload, 900)
        intro_errors = [e for e in errors if "intro" in str(e.get("location", ""))]
        assert intro_errors, "intro 미달은 오류에 role이 포함돼야 한다"
        for e in intro_errors:
            assert e["field"] == "voice"
            assert e["slide_idx"] == 2
            assert "slide_2:intro" in str(e["location"])

    def test_core_slot_short_flagged(self) -> None:
        """core 슬롯이 미달이면 location에 core가 포함된다."""
        payload = self._payload_sections_custom_lengths({"core": 50}, slide_idx=1)
        errors = length_gate_errors(payload, 900)
        core_errors = [e for e in errors if "core" in str(e.get("location", ""))]
        assert core_errors, "core 미달은 오류에 role이 포함돼야 한다"

    def test_multiple_slots_short_multiple_errors(self) -> None:
        """여러 슬롯이 미달이면 각각 별도 오류가 발생한다.

        VoiceSection.text min_length=10이므로 10자 이상이지만 role별 min_chars(80)보다 짧은
        길이를 사용해야 한다(schema 통과 + gate 미달).
        """
        # intro: 15자(>=10 schema OK, <80 gate 미달), closing: 20자(>=10 OK, <80 미달)
        payload = self._payload_sections_custom_lengths({"intro": 15, "closing": 20}, slide_idx=0)
        errors = length_gate_errors(payload, 900)
        roles_in_errors = {
            e["location"].split(":")[-1]
            for e in errors
            if e.get("slide_idx") == 0
        }
        assert "intro" in roles_in_errors
        assert "closing" in roles_in_errors

    def test_legacy_script_text_only_uses_single_gate(self) -> None:
        """sections 없는 레거시 경로는 단일 script_text len() 게이트를 사용한다."""
        payload = parse_payload(
            json.dumps({
                "slides": [_slide(i) for i in range(_SLIDE_COUNT)],
                "quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)],
                "note_blocks": [_note(i) for i in range(4)],
                "assignment": _assignment(),
                "voice_scripts": [
                    {"slide_idx": i, "script_text": "가" * (500 if i == 3 else 950)}
                    for i in range(_SLIDE_COUNT)
                ],
            }, ensure_ascii=False),
            _SLIDE_COUNT,
        )
        errors = length_gate_errors(payload, 900)
        assert len(errors) == 1
        assert errors[0]["slide_idx"] == 3
        # 레거시 경로는 role 구분 없는 단일 location 형식이다.
        assert "slide_3" in str(errors[0]["location"])
        assert ":" not in str(errors[0]["location"]).replace("voice_length_gate:slide_3", "")

    def test_short_voice_indices_matches_errors(self) -> None:
        """short_voice_indices가 length_gate_errors와 같은 slide_idx 집합을 반환한다."""
        payload = self._payload_sections_custom_lengths({"intro": 10}, slide_idx=4)
        errors = length_gate_errors(payload, 900)
        indices = short_voice_indices(payload, 900)
        error_idxs = {int(e["slide_idx"]) for e in errors}
        assert set(indices) == error_idxs

    def test_voice_extend_prompt_references_failed_slot(self) -> None:
        """voice_extend_user_prompt에 미달 슬롯 role이 언급된다."""
        payload = self._payload_sections_custom_lengths({"intro": 10}, slide_idx=0)
        indices = short_voice_indices(payload, 900)
        prompt = voice_extend_user_prompt(payload, indices, 900)
        assert "intro" in prompt, "미달 슬롯 role이 prompt에 있어야 한다"
        assert "줄이거나" in prompt or "축소" in prompt


# ═══════════════════════════════════════════════════════════════════
# E. voice_cohesion — 슬롯 정밀 재작성
# ═══════════════════════════════════════════════════════════════════


class TestVoiceCohesionE:
    """apply_cohesion이 intro 슬롯 text 수준에서 정밀하게 동작하는지 확인.

    sections 구조는 voice_cohesion_pass에서 관리하므로 여기서는 순수 함수 수준만 검증.
    """

    def test_detect_greeting_openings_ignores_slide0(self) -> None:
        """slide_idx==0은 인사말이 있어도 detect_greeting_openings 대상에서 제외된다."""
        from app.modules.ChapterStudio_V1.postprocess.voice_cohesion import detect_greeting_openings
        scripts: list[tuple[int, str]] = [
            (0, "안녕하세요. 첫 슬라이드 인사말입니다."),
            (1, "안녕하세요. 두 번째 슬라이드 인사말입니다."),
            (2, "정수 비교를 직접 해봅시다."),
        ]
        targets = detect_greeting_openings(scripts)
        assert 0 not in targets, "slide_idx=0은 인사 감지 대상 제외"
        assert 1 in targets, "slide_idx=1 인사말은 교정 대상"

    def test_detect_duplicate_openings_excludes_first(self) -> None:
        """detect_duplicate_openings는 첫 항목을 제외하고 중복 인덱스를 반환한다."""
        from app.modules.ChapterStudio_V1.postprocess.voice_cohesion import detect_duplicate_openings
        scripts: list[tuple[int, str]] = [
            (0, "수직선에서 정수를 배웁니다."),
            (1, "수직선에서 정수를 배웁니다."),  # 중복
            (2, "음수 크기 비교를 살펴봅니다."),
        ]
        duplicates = detect_duplicate_openings(scripts)
        assert 0 not in duplicates
        assert 1 in duplicates
        assert 2 not in duplicates

    @pytest.mark.anyio
    async def test_apply_cohesion_only_rewrites_target_text(self) -> None:
        """apply_cohesion은 중복 도입부 슬라이드만 재작성하고 나머지는 불변이다."""
        from app.modules.ChapterStudio_V1.postprocess.voice_cohesion import apply_cohesion

        SAME_OPENING = "수직선에서 정수의 위치를 확인합니다."
        OTHER_TEXT = "이전 화면에서 배운 내용을 이어갑니다."

        scripts: list[tuple[int, str]] = [
            (0, f"{SAME_OPENING} 슬라이드 0 본문."),
            (1, f"{SAME_OPENING} 슬라이드 1 본문."),  # 중복 → 재작성 대상
            (2, f"{OTHER_TEXT} 슬라이드 2 본문."),
        ]

        async def fake_rewrite(prompt: str) -> str:
            return "이번 화면에서는 다음 단계를 살펴봅니다."

        result = await apply_cohesion(scripts, topic="정수와 수직선", rewrite_fn=fake_rewrite)
        by_idx = dict(result)
        # slide 1은 재작성됐어야 한다.
        assert "이번 화면에서는" in by_idx[1], "중복 도입부는 재작성됐어야 한다"
        # slide 1의 나머지 본문(첫 문장 이후)은 보존됐어야 한다.
        assert "슬라이드 1 본문" in by_idx[1], "나머지 본문은 보존돼야 한다"
        # slide 0과 slide 2는 불변이다.
        assert by_idx[0] == scripts[0][1], "slide 0은 불변"
        assert by_idx[2] == scripts[2][1], "slide 2는 불변"


# ═══════════════════════════════════════════════════════════════════
# 헬퍼 — payload 생성용
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
