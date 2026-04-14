"""fallback.py Jinja2 템플릿 단위 테스트.

패키지 __init__.py를 우회해 fallback.py만 직접 로드한다.
jinja2가 설치되지 않은 환경에서는 테스트를 건너뛴다.
"""
import importlib.util
import pathlib
import sys
import pytest

# jinja2 설치 여부 확인 — 없으면 전체 모듈 스킵
jinja2 = pytest.importorskip("jinja2", reason="jinja2가 설치되지 않음 — uv sync 후 재실행")

_BASE = pathlib.Path(__file__).parent.parent

# fallback.py 직접 로드 (패키지 __init__ 우회)
_fallback_spec = importlib.util.spec_from_file_location(
    "app.modules.AI_CPU_Kanana_Nano_Q4.fallback", _BASE / "fallback.py"
)
_fallback_mod = importlib.util.module_from_spec(_fallback_spec)
sys.modules["app.modules.AI_CPU_Kanana_Nano_Q4.fallback"] = _fallback_mod
_fallback_spec.loader.exec_module(_fallback_mod)

render_jinja_caption = _fallback_mod.render_jinja_caption


def test_with_name_and_weakness_and_deadline():
    """이름·약점·마감 모두 있을 때 100자 이내인지 확인한다."""
    result = render_jinja_caption(
        student_name="김민준",
        assignment_name="파이썬 리스트 컴프리헨션",
        weakness="반복문",
        deadline="내일 23:59",
    )
    assert len(result) <= 100, f"100자 초과: {len(result)}자 — '{result}'"


def test_with_name_no_weakness_with_deadline():
    """이름·마감 있고 약점 없을 때 100자 이내인지 확인한다."""
    result = render_jinja_caption(
        student_name="이서연",
        assignment_name="이차방정식 근의 공식 응용 5문제",
        weakness=None,
        deadline="금요일",
    )
    assert len(result) <= 100, f"100자 초과: {len(result)}자 — '{result}'"


def test_with_name_with_weakness_no_deadline():
    """이름·약점 있고 마감 없을 때 100자 이내인지 확인한다."""
    result = render_jinja_caption(
        student_name="박지훈",
        assignment_name="영어 독해 지문 요약",
        weakness="어휘",
        deadline=None,
    )
    assert len(result) <= 100, f"100자 초과: {len(result)}자 — '{result}'"


def test_with_name_no_weakness_no_deadline():
    """이름만 있고 약점·마감 없을 때 100자 이내인지 확인한다."""
    result = render_jinja_caption(
        student_name="최유나",
        assignment_name="자료구조 스택 구현",
        weakness=None,
        deadline=None,
    )
    assert len(result) <= 100, f"100자 초과: {len(result)}자 — '{result}'"


def test_without_name_with_weakness_and_deadline():
    """이름 없이 약점·마감 있을 때 100자 이내인지 확인한다."""
    result = render_jinja_caption(
        student_name="",
        assignment_name="화학 산화-환원 반응 개념 정리",
        weakness="이온화 경향",
        deadline="이번 주 일요일",
    )
    assert len(result) <= 100, f"100자 초과: {len(result)}자 — '{result}'"


def test_without_name_no_weakness_no_deadline():
    """이름·약점·마감 모두 없을 때 100자 이내이고 비어있지 않은지 확인한다."""
    result = render_jinja_caption(
        student_name="",
        assignment_name="수학 미분 기초",
        weakness=None,
        deadline=None,
    )
    assert len(result) <= 100, f"100자 초과: {len(result)}자 — '{result}'"
    assert len(result) > 0, "빈 문자열이 반환됨"


def test_very_long_assignment_truncated():
    """과제명이 매우 길어도 100자 이내로 잘리는지 확인한다."""
    result = render_jinja_caption(
        student_name="홍길동",
        assignment_name="가" * 50,   # 50자짜리 과제명
        weakness="나" * 30,          # 30자짜리 약점
        deadline="다" * 10,          # 10자짜리 마감
    )
    assert len(result) <= 100, f"100자 초과: {len(result)}자 — '{result}'"
