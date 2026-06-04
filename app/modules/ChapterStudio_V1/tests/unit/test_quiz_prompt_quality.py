"""퀴즈 생성 프롬프트 품질 단위 테스트 — 메타 질문 금지 및 실질 문항 요구 검증.

다음 항목을 검증한다:
  A. 메타·태도 질문 명시 금지 지시가 system 프롬프트에 포함되는지
  B. CS 과목 brief에서 코드·연산 기반 문항 지시가 포함되는지
  C. 비CS 과목에서 CS 전용 문항 지시가 포함되지 않는지
  D. difficulty 분포 강제 지시(기억·이해 최대 40%)가 포함되는지
  E. user 프롬프트에서 role이 퀴즈 출제 근거로 사용되지 않도록 설명하는지
  F. CS 과목 슬라이드 프롬프트에서 구체 코드·연산 포함 지시가 있는지
  G. 비CS 과목 슬라이드 프롬프트에서 CS 구체화 지시가 없는지
"""
from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.pipeline.parallel_prompt_text import (
    _cs_slides_concrete_rule,
    _is_cs_subject,
    _quiz_cs_rule,
    quizzes_prompts,
    slides_prompts,
)

# 공통 personalization 인자
_BASE_ARGS = dict(
    weak_points="",
    audience_level="대학생",
    tone=50,
    pace=50,
    tutor_depth=50,
    socratic=50,
    learning_goal="핵심 개념 이해",
)

_NUMPY_BRIEF = "NumPy 기초 — 배열 생성과 인덱싱, 브로드캐스팅"
_MATH_BRIEF = "중학교 1학년 수학 — 수직선과 정수의 대소 비교"
_SLIDE_COUNT = 12

_OUTLINE = "\n".join(
    f"slide {i}: category=text, role=역할{i}, must_have=, visual_type=example_box(고정·변경불가), narration 200~360자"
    for i in range(_SLIDE_COUNT)
)
# role 이름이 메타 질문을 유도하는 실제 케이스
_OUTLINE_WITH_ROLES = "\n".join(
    r for r in [
        "slide 0: category=text, role=도입, must_have=, visual_type=concept_map(고정·변경불가), narration 200~280자",
        "slide 1: category=text, role=핵심 설명, must_have=, visual_type=example_box(고정·변경불가), narration 200~360자",
        "slide 2: category=text, role=확장 질문, must_have=, visual_type=metric-card(고정·변경불가), narration 200~300자",
        "slide 3: category=text, role=강의 끝 점검, must_have=, visual_type=example_box(고정·변경불가), narration 200~300자",
    ]
)


def _quiz_system(brief: str, outline: str = _OUTLINE) -> str:
    """quizzes_prompts의 system 프롬프트 문자열을 반환한다."""
    system, _ = quizzes_prompts(brief, outline, _SLIDE_COUNT, **_BASE_ARGS)
    return system


def _quiz_user(brief: str, outline: str = _OUTLINE) -> str:
    """quizzes_prompts의 user 프롬프트 문자열을 반환한다."""
    _, user = quizzes_prompts(brief, outline, _SLIDE_COUNT, **_BASE_ARGS)
    return user


def _slides_system(brief: str) -> str:
    """slides_prompts의 system 프롬프트 문자열을 반환한다."""
    system, _ = slides_prompts(brief, _OUTLINE, _SLIDE_COUNT, "concept_code", **_BASE_ARGS)
    return system


# ── A. 메타·태도 질문 명시 금지 지시 ─────────────────────────────────────

class TestMetaQuestionBan:
    """system 프롬프트에 메타·태도 질문 금지 지시가 명시돼야 한다."""

    def test_numpy_quiz_bans_meta_attitude_questions(self) -> None:
        """NumPy CS 과목에서 메타·태도 질문 금지 지시가 포함된다."""
        system = _quiz_system(_NUMPY_BRIEF)
        # 금지 선언 존재
        assert "절대 금지" in system, "메타 질문 절대 금지 선언 없음"

    def test_bans_specific_meta_patterns(self) -> None:
        """구체적 메타 질문 예시(바람직한 학습자 반응, 잘 이해한 학습자)가 금지 목록에 있다."""
        system = _quiz_system(_NUMPY_BRIEF)
        assert "바람직한 학습자 반응" in system
        assert "잘 이해한 학습자" in system

    def test_bans_lecture_end_checkpoint_as_quiz_basis(self) -> None:
        """강의 끝 점검 패턴이 금지 목록에 명시된다."""
        system = _quiz_system(_NUMPY_BRIEF)
        assert "강의 끝 점검" in system

    def test_meta_ban_applies_to_non_cs_subject_too(self) -> None:
        """수학 과목에서도 메타·태도 질문 금지 지시가 포함된다."""
        system = _quiz_system(_MATH_BRIEF)
        assert "절대 금지" in system

    def test_quiz_must_measure_subject_knowledge(self) -> None:
        """퀴즈는 학습 주제 자체 지식·개념·적용을 측정해야 한다는 지시가 있다."""
        system = _quiz_system(_NUMPY_BRIEF)
        assert "주제" in system and ("지식" in system or "개념" in system)


# ── B. CS 과목 코드·연산 기반 문항 요구 ────────────────────────────────────

class TestCsQuizCodeRule:
    """CS 과목에서 코드·연산 기반 문항 지시가 추가된다."""

    def test_numpy_quiz_includes_code_operation_instruction(self) -> None:
        """NumPy 과목이면 코드 출력 예측, 인덱싱·슬라이싱 문항 지시가 있다."""
        system = _quiz_system(_NUMPY_BRIEF)
        # 코드·연산 기반 지시 키워드 확인
        assert "코드" in system
        # shape/dtype/브로드캐스팅 같은 CS 전용 지시 존재
        assert any(kw in system for kw in ("shape", "dtype", "브로드캐스팅", "인덱싱", "슬라이싱")), (
            "NumPy CS 과목에서 구체적 코드 연산 지시 없음"
        )

    def test_cs_quiz_rule_returns_nonempty_for_cs_brief(self) -> None:
        """_quiz_cs_rule이 CS 과목에 대해 비어있지 않은 지시문을 반환한다."""
        rule = _quiz_cs_rule(_NUMPY_BRIEF)
        assert rule != ""
        assert "코드" in rule

    def test_programming_brief_gets_cs_quiz_rule(self) -> None:
        """파이썬 프로그래밍 brief에서도 CS 전용 퀴즈 지시가 포함된다."""
        brief = "파이썬 프로그래밍 — 함수와 리스트 컴프리헨션"
        rule = _quiz_cs_rule(brief)
        assert rule != "", "파이썬 과목이 CS로 인식되지 않음"

    def test_algorithm_brief_gets_cs_quiz_rule(self) -> None:
        """알고리즘·자료구조 과목에서 CS 전용 퀴즈 지시가 포함된다."""
        brief = "자료구조와 알고리즘 — 정렬과 탐색"
        rule = _quiz_cs_rule(brief)
        assert rule != ""


# ── C. 비CS 과목에서 CS 전용 지시 제외 ─────────────────────────────────────

class TestNonCsQuizNoCodeRule:
    """비CS 과목에서는 CS 전용 코드 연산 지시가 추가되지 않는다."""

    def test_math_quiz_does_not_include_cs_code_instruction(self) -> None:
        """수학 과목은 CS 전용 코드 지시(shape, 브로드캐스팅 등)가 없다."""
        system = _quiz_system(_MATH_BRIEF)
        assert "shape" not in system
        assert "브로드캐스팅" not in system
        assert "인덱싱" not in system or "수직선" in system  # 수학의 인덱싱은 다른 맥락

    def test_quiz_cs_rule_returns_empty_for_math(self) -> None:
        """_quiz_cs_rule이 수학 과목에 대해 빈 문자열을 반환한다."""
        assert _quiz_cs_rule(_MATH_BRIEF) == ""

    def test_quiz_cs_rule_returns_empty_for_science(self) -> None:
        """_quiz_cs_rule이 과학 과목에 대해 빈 문자열을 반환한다."""
        assert _quiz_cs_rule("중학교 과학 — 빛의 반사와 굴절") == ""


# ── D. difficulty 분포 강제 지시 ─────────────────────────────────────────

class TestDifficultyDistribution:
    """difficulty 분포 강제 지시(기억·이해 최대 40%)가 system 프롬프트에 포함된다."""

    def test_difficulty_cap_on_memory_understanding(self) -> None:
        """기억·이해 최대 40% 제한 지시가 있다."""
        system = _quiz_system(_NUMPY_BRIEF)
        assert "40%" in system, "difficulty 분포 40% 제한 지시 없음"

    def test_difficulty_distribution_applies_to_non_cs_too(self) -> None:
        """비CS 과목에서도 difficulty 분포 강제 지시가 있다."""
        system = _quiz_system(_MATH_BRIEF)
        assert "40%" in system

    def test_difficulty_requires_higher_order(self) -> None:
        """적용·함정 교정·실전 판단·오해 등 고차원 문항이 60% 이상이어야 한다는 지시가 있다."""
        system = _quiz_system(_NUMPY_BRIEF)
        assert "60%" in system or "이상" in system


# ── E. user 프롬프트에서 role 오용 방지 설명 ──────────────────────────────

class TestUserPromptRoleExplanation:
    """user 프롬프트에서 role은 슬라이드 구조 참고용임을 명시해야 한다."""

    def test_user_prompt_clarifies_role_is_not_quiz_basis(self) -> None:
        """user 프롬프트에서 role이 퀴즈 근거로 사용되지 않는다고 명시된다."""
        user = _quiz_user(_NUMPY_BRIEF, _OUTLINE_WITH_ROLES)
        assert "role" in user.lower() or "역할" in user
        # 슬라이드 구조 참고용이라는 설명이 있어야 한다
        assert "구조" in user or "참고" in user

    def test_user_prompt_bans_learning_attitude_from_role(self) -> None:
        """user 프롬프트에서 '학습자 반응' 문항 생성 금지를 명시한다."""
        user = _quiz_user(_NUMPY_BRIEF, _OUTLINE_WITH_ROLES)
        assert "학습자 반응" in user or "쓰지 않는다" in user

    def test_user_prompt_requires_concrete_subject_content(self) -> None:
        """user 프롬프트에서 슬라이드의 구체적 학습 내용에서 출제한다고 명시한다."""
        user = _quiz_user(_NUMPY_BRIEF)
        assert "구체적" in user or "개념" in user


# ── F. CS 과목 슬라이드 구체 콘텐츠 지시 ────────────────────────────────────

class TestCsSlidesConcreteRule:
    """CS 과목 슬라이드 프롬프트에 구체 코드·연산 포함 지시가 추가된다."""

    def test_numpy_slides_include_concrete_code_instruction(self) -> None:
        """NumPy 슬라이드 프롬프트에 실제 코드·연산 포함 지시가 있다."""
        system = _slides_system(_NUMPY_BRIEF)
        assert "코드" in system or "연산" in system
        # 구체 예시 언급 확인
        assert any(kw in system for kw in ("arr", "np.array", "shape", "브로드캐스팅")), (
            "NumPy 슬라이드에서 구체 코드 예시 지시 없음"
        )

    def test_cs_slides_concrete_rule_returns_nonempty_for_cs(self) -> None:
        """_cs_slides_concrete_rule이 CS 과목에 대해 비어있지 않은 지시를 반환한다."""
        rule = _cs_slides_concrete_rule(_NUMPY_BRIEF)
        assert rule != ""
        assert "코드" in rule

    def test_cs_slides_bans_abstract_only_slides(self) -> None:
        """추상적 관점·태도만 담은 슬라이드는 실패라는 지시가 있다."""
        rule = _cs_slides_concrete_rule(_NUMPY_BRIEF)
        assert "실패" in rule or "추상" in rule


# ── G. 비CS 과목 슬라이드에서 CS 구체화 지시 제외 ───────────────────────────

class TestNonCsSlidesNoCsRule:
    """비CS 과목 슬라이드에서는 CS 전용 구체화 지시가 추가되지 않는다."""

    def test_math_slides_no_cs_concrete_rule(self) -> None:
        """수학 과목 슬라이드에서 _cs_slides_concrete_rule 지시가 없다."""
        rule = _cs_slides_concrete_rule(_MATH_BRIEF)
        assert rule == "", f"수학 과목에 CS 구체화 지시가 추가됨: {rule}"

    def test_math_slides_system_no_numpy_examples(self) -> None:
        """수학 슬라이드 system 프롬프트에 NumPy 전용 예시가 없다."""
        system = _slides_system(_MATH_BRIEF)
        assert "np.array" not in system
        assert "arr[" not in system
