"""title_rules 단일 진실 소스 검증 (P2-2·P2-3).

챕터명+번호 제목 감지 정규식의 정확성을 검증한다:
    - 의뢰 명시 반례: '3단원 2번'(끝이 번), '일차함수 y=ax+b 12'(수식 과잉매칭)
    - parallel_prompts·visual_quality가 동일 로직(단일 소스)을 쓰는지(중복 제거 확인)
"""
from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.postprocess.title_rules import (
    is_chapter_number_title,
    relabel_chapter_title,
)
from app.modules.ChapterStudio_V1.postprocess.visual_quality import (
    relabel_chapter_title as vq_relabel,
)
from app.modules.ChapterStudio_V1.pipeline.parallel_prompts import _relabel_chapter_title


# 재라벨 대상(챕터명+번호) — True여야 한다.
_BAD_TITLES = [
    "수직선과 정수의 위치 3",   # 본문+공백+숫자
    "3단원 2번",                # 끝이 '번' (의뢰 명시 반례)
    "함수 개념 5장",            # 끝이 '장'
    "정수의 덧셈 2차시",        # 끝이 '차시'
    "함수의 개념과 표현 5",     # 본문+공백+숫자
    "이차함수 그래프 12",       # 두 자리 숫자
]

# 정상 제목 — False여야 한다(재라벨 금지).
_GOOD_TITLES = [
    "음수끼리의 크기 비교",
    "일차함수 y=ax+b 12",       # 수식 포함 (의뢰 명시 — 과잉매칭 회피)
    "이차방정식 x^2=4의 해",    # 수식 포함
    "2배 하는 방법",            # 숫자가 앞·중간
    "핵심 개념 이해",
    "3+4 계산하기",             # 연산식
]


@pytest.mark.parametrize("title", _BAD_TITLES)
def test_chapter_number_titles_detected(title: str) -> None:
    """챕터명+번호 형태 제목을 모두 감지한다(번/장/차시 단위어 포함)."""
    assert is_chapter_number_title(title) is True, f"감지 실패: {title!r}"


@pytest.mark.parametrize("title", _GOOD_TITLES)
def test_normal_titles_not_detected(title: str) -> None:
    """정상 제목·수식 제목을 챕터명+번호로 오인하지 않는다(과잉매칭 회피)."""
    assert is_chapter_number_title(title) is False, f"과잉매칭: {title!r}"


def test_relabel_uses_must_have_first_item() -> None:
    """재라벨은 must_have 첫 항목을 16자 이내로 잘라 적용한다."""
    result = relabel_chapter_title("수직선과 정수의 위치 3", ["음수 크기 비교"])
    assert result == "음수 크기 비교"


def test_relabel_keeps_normal_title() -> None:
    """정상 제목은 must_have가 있어도 변경하지 않는다."""
    assert relabel_chapter_title("음수끼리의 크기 비교", ["핵심"]) == "음수끼리의 크기 비교"


def test_relabel_keeps_formula_title() -> None:
    """수식 제목은 must_have가 있어도 재라벨하지 않는다(과잉매칭 회피)."""
    assert relabel_chapter_title("일차함수 y=ax+b 12", ["기울기"]) == "일차함수 y=ax+b 12"


def test_relabel_no_must_have_keeps_title() -> None:
    """must_have가 없으면 챕터명+번호 제목도 유지한다."""
    assert relabel_chapter_title("함수 5장", None) == "함수 5장"
    assert relabel_chapter_title("함수 5장", []) == "함수 5장"


def test_single_source_visual_quality_delegates() -> None:
    """visual_quality.relabel_chapter_title이 title_rules와 동일 결과를 낸다(단일 소스)."""
    for title in _BAD_TITLES + _GOOD_TITLES:
        assert vq_relabel(title, ["대체 개념"]) == relabel_chapter_title(title, ["대체 개념"])


def test_single_source_parallel_prompts_delegates() -> None:
    """parallel_prompts._relabel_chapter_title이 title_rules와 동일 결과를 낸다(단일 소스)."""
    plan_slot = {"must_have": ["대체 개념"]}
    for title in _BAD_TITLES + _GOOD_TITLES:
        via_prompts = _relabel_chapter_title(title, plan_slot)
        via_rules = relabel_chapter_title(title, ["대체 개념"])
        assert via_prompts == via_rules, f"불일치: {title!r}"
