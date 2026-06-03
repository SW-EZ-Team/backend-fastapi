"""B항: ExamForge 해설 완결성 게이트 단위 테스트.

LLM 실호출 없이 순수 함수로 검증한다:
    - 미완성 해설(truncation) → is_explanation_complete=False
    - 완성 해설 → is_explanation_complete=True
    - validate_node._check_single_structure가 미완성 해설을 실패로 분류하는지
"""
from __future__ import annotations

import pytest

from app.modules.ExamForge_V1.quality.explanation_checker import (
    check_explanation_quality,
    is_explanation_complete,
)


# ── is_explanation_complete 단위 테스트 ─────────────────────────────────

def test_complete_explanation_passes() -> None:
    """완결된 해설(종결 어미 + 충분한 길이) → True."""
    explanation = (
        "정답은 2번 애자일 방법론입니다. 반복적이고 유연한 개발을 강조하며 변화에 신속하게 대응하는 것이 특징입니다. "
        "나머지 보기들은 폭포수 모델의 순차적 특징에 해당합니다."
    )
    assert is_explanation_complete(explanation) is True


def test_short_but_complete_explanation_passes() -> None:
    """P2-B 회귀: 짧지만 정상 종결로 끝나는 해설은 통과한다(오탐 해소)."""
    # "정답은 2번이며 ... 모두 제외된다." 류 — 53자 이하 완결 해설이 truncation으로 오탐되면 안 됨.
    explanation = "정답은 2번이며 1번 3번 4번은 모두 조건을 충족하지 못해 제외된다."
    assert is_explanation_complete(explanation) is True


def test_short_complete_with_요_ending_passes() -> None:
    """P2-B 회귀: 매우 짧아도 '요'/'다' 종결이면 완결로 본다."""
    assert is_explanation_complete("정답은 A입니다.") is True


def test_near_empty_stub_fails() -> None:
    """절대 최소 길이 미만의 빈 스텁 해설은 미완성으로 본다."""
    assert is_explanation_complete("정답.") is False


def test_ending_with_conjunction_fails() -> None:
    """조사/접속어로 끝나는 해설 → 문장 중간 끊김, False."""
    explanation = (
        "정답은 2번입니다. 애자일 방법론은 변화에 유연하게 대응하며 "
        "1번 폭포수는 순차적 단계이고 2번은 반복적 개발을 강조하며 "
        "짧은 주기의 개발을 통해 요구사항 변화에 신속하게"  # 문장이 여기서 끊김
    )
    assert is_explanation_complete(explanation) is False


def test_ending_without_sentence_terminator_fails() -> None:
    """종결 부호 없이 끝나는 해설 → False."""
    # '다' 나 '요'로 끝나지 않고 일반 명사로 끝나는 경우
    explanation = (
        "정답은 2번 애자일 방법론이며 이는 반복적 개발 방식의 특징을 가진 "
        "개발 방법론입니다. 나머지 보기들은 폭포수 모델의 특징에 해당하는 개발 방법론"
    )
    assert is_explanation_complete(explanation) is False


def test_empty_explanation_fails() -> None:
    """빈 해설 → False."""
    assert is_explanation_complete("") is False


def test_whitespace_only_explanation_fails() -> None:
    """공백만 있는 해설 → False."""
    assert is_explanation_complete("   ") is False


# ── check_explanation_quality 완결성 게이트 통합 테스트 ─────────────────

def test_check_quality_flags_truncated_explanation() -> None:
    """check_explanation_quality가 문장 중간 끊긴(truncated) 해설을 이슈로 반환한다."""
    question = {
        "stem": "다음 중 애자일의 특징은?",
        "options": [
            {"label": "1", "text": "순차적", "is_correct": False},
            {"label": "2", "text": "반복적", "is_correct": True},
            {"label": "3", "text": "문서 중심", "is_correct": False},
            {"label": "4", "text": "단일 릴리즈", "is_correct": False},
        ],
        "correct_answer": "2",
        # 종결 부호 없이 조사로 끊겨 truncation 의심('대응하며'에서 중단)
        "explanation": "정답은 2번이며 1번 3번 4번은 폭포수 모델의 특징이고 변화에 유연하게 대응하며",
    }
    issues = check_explanation_quality(question)
    # truncation 관련 이슈가 반환돼야 한다
    assert any(
        "truncation" in i or "끊겨" in i or "완결" in i
        for i in issues
    ), f"예상한 이슈 없음: {issues}"


def test_check_quality_passes_complete_explanation() -> None:
    """완결된 해설은 완결성 이슈 없이 통과한다."""
    question = {
        "stem": "다음 중 애자일의 특징은?",
        "options": [
            {"label": "1", "text": "순차적", "is_correct": False},
            {"label": "2", "text": "반복적", "is_correct": True},
            {"label": "3", "text": "문서 중심", "is_correct": False},
            {"label": "4", "text": "단일 릴리즈", "is_correct": False},
        ],
        "correct_answer": "2",
        "explanation": (
            "정답은 2번 반복적 개발 방식이며 이것이 애자일 방법론의 핵심 특징입니다. "
            "1번 순차적 진행은 폭포수 모델의 특징으로 각 단계가 완료되어야 다음으로 넘어갑니다. "
            "3번 문서 중심 개발은 전통적 방법론의 특징으로 애자일과 반대됩니다. "
            "4번 단일 릴리즈 주기는 폭포수 모델에 가까운 방식입니다."
        ),
    }
    issues = check_explanation_quality(question)
    # 완결성 관련 이슈는 없어야 한다
    completeness_issues = [
        i for i in issues
        if "truncation" in i or "짧아" in i or "완결" in i
    ]
    assert completeness_issues == [], f"예상치 않은 완결성 이슈: {completeness_issues}"
