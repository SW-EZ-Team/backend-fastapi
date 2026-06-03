"""C항·D항: voice 프롬프트 강화 및 코딩 메타포 금지 단위 테스트.

C항 — voice 섹션 길이 지시 강화:
    - _build_slot_spec이 최소 분량 강제 문구를 포함하는지
    - 최소 분량 미달 시 repair 루프가 충족으로 보완하는지(voice_length_gate)

D항 — 비CS 과목 코딩 메타포 금지:
    - _is_cs_subject가 CS/비CS를 올바르게 판별하는지
    - 비CS 과목 slides_prompts system에 금지 지시가 포함되는지
    - CS 과목 slides_prompts system에 금지 지시가 없는지
"""
from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.pipeline.parallel_prompt_text import (
    _build_slot_spec,
    _is_cs_subject,
    _coding_metaphor_rule,
    slides_prompts,
    voice_prompt,
)
from app.modules.ChapterStudio_V1.pipeline.parallel_inputs import build_voice_blueprint
from app.modules.ChapterStudio_V1.pipeline.voice_length_gate import (
    length_gate_errors,
    short_voice_indices,
    voice_extend_user_prompt,
)
from app.modules.ChapterStudio_V1.pipeline.payload import parse_payload


# ── C항: _build_slot_spec 강제 문구 포함 테스트 ─────────────────────────

def test_slot_spec_contains_min_chars_mandate() -> None:
    """_build_slot_spec이 각 슬롯에 최소 분량 강제 문구를 포함한다."""
    blueprint = build_voice_blueprint(slide_idx=0, previous_title="")
    spec = _build_slot_spec(blueprint)
    # 강제 문구 핵심 키워드 존재 확인
    assert "이상" in spec, "최소 분량 기준 문구 없음"
    assert "거부" in spec or "재생성" in spec, "재생성 경고 문구 없음"


def test_slot_spec_contains_role_specific_limits() -> None:
    """_build_slot_spec이 role별로 서로 다른 길이 요건을 포함한다."""
    blueprint = build_voice_blueprint(slide_idx=1, previous_title="이전 슬라이드")
    spec = _build_slot_spec(blueprint)
    # 4개 role 모두 포함되어야 한다
    for role in ("intro", "core", "example", "closing"):
        assert role in spec, f"role={role} 슬롯 명세 누락"


def test_slot_spec_first_slide_greeting_mode() -> None:
    """slide_idx=0이면 intro에 greeting 모드 표시가 있다."""
    blueprint = build_voice_blueprint(slide_idx=0, previous_title="")
    spec = _build_slot_spec(blueprint)
    assert "greeting" in spec


def test_slot_spec_non_first_slide_bridge_mode() -> None:
    """slide_idx>0이면 intro에 bridge 모드 표시가 있다."""
    blueprint = build_voice_blueprint(slide_idx=2, previous_title="앞 슬라이드")
    spec = _build_slot_spec(blueprint)
    assert "bridge" in spec


# ── C항: voice_length_gate repair 보완 테스트 ───────────────────────────

_SLIDE_COUNT = 10
_MIN_CHARS = 900


def _make_payload_with_sections(short_idx: int, short_role: str, short_chars: int):
    """첫 패스 미달 시나리오 — sections 포함 payload."""
    from app.modules.ChapterStudio_V1.common.config import VOICE_SECTION_RANGES

    def _make_voice_script(idx: int) -> dict:
        # 정상 슬라이드는 각 role을 min 이상으로 채운다
        sections = []
        for role in ("intro", "core", "example", "closing"):
            min_c, max_c = VOICE_SECTION_RANGES[role]
            char_count = short_chars if (idx == short_idx and role == short_role) else min_c
            sections.append({"role": role, "text": "가" * char_count})
        return {"slide_idx": idx, "script_text": "", "sections": sections}

    raw = {
        "slides": [_slide(i) for i in range(_SLIDE_COUNT)],
        "quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)],
        "note_blocks": [_note(i) for i in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [_make_voice_script(i) for i in range(_SLIDE_COUNT)],
    }
    return parse_payload(json.dumps(raw, ensure_ascii=False), _SLIDE_COUNT)


def test_first_pass_underrun_detected_by_gate() -> None:
    """첫 패스에서 core 슬롯이 min 미달인 경우 길이 게이트가 탐지한다."""
    from app.modules.ChapterStudio_V1.common.config import VOICE_SECTION_RANGES

    core_min = VOICE_SECTION_RANGES["core"][0]
    # core를 min의 78% 수준으로 짧게 설정(실생성 패턴 반영)
    short_core = int(core_min * 0.78)
    payload = _make_payload_with_sections(short_idx=0, short_role="core", short_chars=short_core)

    errors = length_gate_errors(payload, _MIN_CHARS)
    # slide 0의 core 슬롯 오류가 감지돼야 한다
    slide0_errors = [e for e in errors if int(e.get("slide_idx", -1)) == 0]
    assert slide0_errors, "첫 패스 미달이 게이트에서 탐지되지 않음"


def test_repair_prompt_covers_short_slot() -> None:
    """repair 프롬프트가 미달 슬롯을 포함하는 확장 지시를 생성한다."""
    from app.modules.ChapterStudio_V1.common.config import VOICE_SECTION_RANGES

    core_min = VOICE_SECTION_RANGES["core"][0]
    short_core = int(core_min * 0.78)
    payload = _make_payload_with_sections(short_idx=0, short_role="core", short_chars=short_core)

    short_indices = short_voice_indices(payload, _MIN_CHARS)
    assert 0 in short_indices, "미달 slide_idx가 short_indices에 없음"

    prompt = voice_extend_user_prompt(payload, short_indices, _MIN_CHARS)
    # repair 프롬프트가 미달 슬롯의 현재 내용을 담고 있어야 한다
    assert "slide 0" in prompt
    assert "core" in prompt
    assert "이상" in prompt or "확장" in prompt


def test_gate_passes_when_all_sections_sufficient() -> None:
    """모든 섹션이 min 이상이면 게이트 오류 없음."""
    from app.modules.ChapterStudio_V1.common.config import VOICE_SECTION_RANGES

    def _make_full_voice_script(idx: int) -> dict:
        sections = []
        for role in ("intro", "core", "example", "closing"):
            min_c, _ = VOICE_SECTION_RANGES[role]
            sections.append({"role": role, "text": "가" * (min_c + 10)})
        return {"slide_idx": idx, "script_text": "", "sections": sections}

    raw = {
        "slides": [_slide(i) for i in range(_SLIDE_COUNT)],
        "quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)],
        "note_blocks": [_note(i) for i in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [_make_full_voice_script(i) for i in range(_SLIDE_COUNT)],
    }
    payload = parse_payload(json.dumps(raw, ensure_ascii=False), _SLIDE_COUNT)

    errors = length_gate_errors(payload, _MIN_CHARS)
    assert errors == [], f"충분한 섹션인데 오류 발생: {errors}"


# ── D항: _is_cs_subject 판별 테스트 ─────────────────────────────────────

def test_is_cs_subject_programming() -> None:
    """프로그래밍 과목 brief → True."""
    assert _is_cs_subject("파이썬 프로그래밍 기초 — 변수와 자료형") is True


def test_is_cs_subject_algorithm() -> None:
    """알고리즘 과목 → True."""
    assert _is_cs_subject("알고리즘과 자료구조 — 정렬과 탐색") is True


def test_is_cs_subject_math() -> None:
    """수학 과목 → False."""
    assert _is_cs_subject("중학교 1학년 수학 — 정수와 유리수 비교") is False


def test_is_cs_subject_science() -> None:
    """과학 과목 → False."""
    assert _is_cs_subject("중학교 과학 — 빛의 반사와 굴절") is False


def test_is_cs_subject_korean_literature() -> None:
    """국어 과목 → False."""
    assert _is_cs_subject("국어 문학 — 시의 운율과 이미지") is False


# ── D항(P2-D 회귀): 수학 단원어가 CS로 오분류되지 않는지 ─────────────────

def test_math_function_not_cs() -> None:
    """P2-D 회귀: '함수'는 수학 단원어이므로 CS로 오분류되면 안 된다."""
    assert _is_cs_subject("이차함수의 그래프와 최댓값") is False


def test_math_euclidean_algorithm_not_cs() -> None:
    """P2-D 회귀: '유클리드 호제법 알고리즘'은 수학이므로 CS가 아니다."""
    assert _is_cs_subject("유클리드 호제법 알고리즘으로 최대공약수 구하기") is False


def test_math_linear_function_not_cs() -> None:
    """P2-D 회귀: '일차함수'는 수학이므로 CS가 아니다."""
    assert _is_cs_subject("일차함수와 기울기") is False


def test_math_function_gets_coding_ban() -> None:
    """P2-D 회귀: 수학-함수 brief는 코딩 메타포 금지 지시를 받는다(비CS)."""
    rule = _coding_metaphor_rule("이차함수의 그래프")
    assert "금지" in rule or "쓰지 않" in rule, "수학-함수가 비CS로 분류되지 않아 금지 지시 누락"


def test_cs_algorithm_with_context_is_cs() -> None:
    """'정렬 알고리즘 (python)'처럼 CS 맥락어와 함께면 CS로 인정한다."""
    assert _is_cs_subject("정렬 알고리즘 구현 (python)") is True


def test_cs_data_structure_is_cs() -> None:
    """'자료구조와 알고리즘'은 CS로 분류한다."""
    assert _is_cs_subject("자료구조와 알고리즘 — 정렬") is True


# ── D항: slides_prompts system에 코딩 메타포 금지 지시 테스트 ────────────

def _default_kwargs() -> dict:
    return dict(
        outline="slide 0: category=text, visual_type=example_box",
        slide_count=1,
        template_key="default",
        weak_points="",
        audience_level="중학생",
        tone=50,
        pace=50,
        tutor_depth=50,
        socratic=70,
        learning_goal="핵심 개념 이해",
    )


def test_non_cs_brief_includes_coding_metaphor_ban() -> None:
    """비CS 과목 brief → system 프롬프트에 코딩 메타포 금지 지시 포함."""
    brief = "중학교 1학년 수학 — 정수와 수직선"
    system, _ = slides_prompts(brief, **_default_kwargs())
    # 금지 키워드 중 하나 이상이 포함되어야 한다
    assert any(kw in system for kw in ("코딩", "프로그래밍", "class처럼", "def처럼")), (
        "비CS 과목에서 코딩 메타포 금지 지시가 system 프롬프트에 없음"
    )
    # 금지 방향('금지')이 명시되어야 한다
    assert "금지" in system or "쓰지 않" in system, "금지 지시 문구 없음"


def test_cs_brief_does_not_include_coding_ban() -> None:
    """CS 과목 brief → system 프롬프트에 코딩 메타포 금지 지시 없음."""
    brief = "파이썬 프로그래밍 — 함수와 클래스 기초"
    system, _ = slides_prompts(brief, **_default_kwargs())
    # CS 과목이면 금지 지시 없이 생성돼야 한다
    # (_coding_metaphor_rule이 빈 문자열을 반환)
    coding_ban_text = _coding_metaphor_rule(brief)
    assert coding_ban_text == "", f"CS 과목에서 코딩 메타포 금지 지시가 추가됨: {coding_ban_text}"


def test_coding_metaphor_rule_non_cs_contains_ban() -> None:
    """_coding_metaphor_rule이 비CS 과목에서 금지 지시 문자열을 반환한다."""
    rule = _coding_metaphor_rule("고등학교 물리 — 역학적 에너지")
    assert "금지" in rule or "쓰지 않" in rule
    assert "class처럼" in rule


def test_coding_metaphor_rule_cs_returns_empty() -> None:
    """_coding_metaphor_rule이 CS 과목에서 빈 문자열을 반환한다."""
    assert _coding_metaphor_rule("알고리즘과 자료구조 강의") == ""


# ── 보조 빌더 ────────────────────────────────────────────────────────────

def _slide(idx: int) -> dict:
    return {
        "slide_idx": idx,
        "title": f"슬라이드 {idx}",
        "focus": "핵심 개념",
        "checkpoint": "이해했나요?",
        "category": "text",
        "html": "<section><p>핵심 개념을 단계별로 설명합니다.</p></section>",
        "css": "",
    }


def _quiz(idx: int) -> dict:
    return {
        "slide_idx": idx,
        "question": "다음 중 올바른 것은?",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "이해",
        "explanation": "정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 오답입니다.",
    }


def _note(idx: int) -> dict:
    return {
        "heading": f"핵심 정리 {idx}",
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
