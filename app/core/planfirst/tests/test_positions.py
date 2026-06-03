"""positions.py byte-identical 증명 테스트.

핵심 목적:
  1. balanced_target_positions / seed_from_key 기본 동작
  2. 추출 전(복제 구현) 대비 byte-identical 출력 검증
     - ChapterStudio quiz_balance.balanced_target_positions
     - ExamForge concept_blueprint._balanced_target_positions
  3. 엣지케이스 (count=0, num_choices=1, 음수 입력)
"""
from __future__ import annotations

import hashlib
import random

import pytest

from app.core.planfirst.positions import balanced_target_positions, seed_from_key


# ── 추출 전 원본 구현(레퍼런스) ─────────────────────────────────────────────


def _ref_cs_balanced(count: int, num_choices: int = 4, seed: int = 0) -> list[int]:
    """ChapterStudio quiz_balance.py 원본 알고리즘(추출 전 복사본)."""
    if count < 0:
        raise ValueError("count는 0 이상이어야 한다.")
    if num_choices < 1:
        raise ValueError("num_choices는 1 이상이어야 한다.")
    positions = [idx % num_choices for idx in range(count)]
    random.Random(seed).shuffle(positions)
    return positions


def _ref_ef_balanced(count: int, num_choices: int = 4, seed: int = 0) -> list[int]:
    """ExamForge concept_blueprint.py 원본 알고리즘(추출 전 복사본)."""
    if count <= 0:
        return []
    positions = [idx % num_choices for idx in range(count)]
    random.Random(seed).shuffle(positions)
    return positions


def _ref_cs_seed(seed_key: str) -> int:
    """ChapterStudio quiz_balance.py _seed_from_key 원본."""
    if seed_key == "":
        return 0
    digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _ref_ef_seed(seed_key: str) -> int:
    """ExamForge concept_blueprint.py _seed_from_key 원본."""
    if not seed_key:
        return 0
    digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


# ── byte-identical 증명 ────────────────────────────────────────────────────


@pytest.mark.parametrize("count", [1, 2, 5, 10, 20, 50, 100])
@pytest.mark.parametrize("num_choices", [4, 5])
@pytest.mark.parametrize("seed", [0, 42, 999, 1_000_000])
def test_byte_identical_vs_chapterstudio(count: int, num_choices: int, seed: int) -> None:
    """단일 소스 출력이 ChapterStudio 원본과 byte-identical임을 증명한다."""
    expected = _ref_cs_balanced(count, num_choices, seed)
    actual = balanced_target_positions(count, num_choices, seed)
    assert actual == expected, (
        f"ChapterStudio 불일치: count={count}, nc={num_choices}, seed={seed}"
    )


@pytest.mark.parametrize("count", [1, 2, 5, 10, 20, 50, 100])
@pytest.mark.parametrize("num_choices", [4, 5])
@pytest.mark.parametrize("seed", [0, 42, 999, 1_000_000])
def test_byte_identical_vs_examforge(count: int, num_choices: int, seed: int) -> None:
    """단일 소스 출력이 ExamForge 원본과 byte-identical임을 증명한다."""
    expected = _ref_ef_balanced(count, num_choices, seed)
    actual = balanced_target_positions(count, num_choices, seed)
    assert actual == expected, (
        f"ExamForge 불일치: count={count}, nc={num_choices}, seed={seed}"
    )


@pytest.mark.parametrize("key", ["", "test_key", "exam_123", "한글키", "  spaces  "])
def test_seed_from_key_identical_to_chapterstudio(key: str) -> None:
    """seed_from_key가 ChapterStudio 원본과 byte-identical임을 증명한다."""
    assert seed_from_key(key) == _ref_cs_seed(key)


@pytest.mark.parametrize("key", ["", "test_key", "exam_123", "한글키", "  spaces  "])
def test_seed_from_key_identical_to_examforge(key: str) -> None:
    """seed_from_key가 ExamForge 원본과 byte-identical임을 증명한다."""
    assert seed_from_key(key) == _ref_ef_seed(key)


# ── 기본 동작 ─────────────────────────────────────────────────────────────


def test_count_zero_returns_empty() -> None:
    assert balanced_target_positions(0) == []
    assert balanced_target_positions(0, num_choices=5, seed=42) == []


def test_length_equals_count() -> None:
    for count in [1, 7, 15]:
        result = balanced_target_positions(count)
        assert len(result) == count


def test_all_values_in_range() -> None:
    result = balanced_target_positions(20, num_choices=4, seed=0)
    assert all(0 <= v < 4 for v in result)


def test_even_distribution_large_count() -> None:
    """4배수 count에서 0..3이 정확히 균등 분포함을 확인한다."""
    result = balanced_target_positions(100, num_choices=4, seed=0)
    counts = {v: result.count(v) for v in range(4)}
    assert all(c == 25 for c in counts.values()), f"분포 불균등: {counts}"


def test_deterministic_same_seed() -> None:
    """같은 seed면 항상 동일 결과를 반환한다."""
    r1 = balanced_target_positions(10, num_choices=4, seed=77)
    r2 = balanced_target_positions(10, num_choices=4, seed=77)
    assert r1 == r2


def test_different_seeds_produce_different_order() -> None:
    """다른 seed는 (충분히 큰 count에서) 다른 순서를 만든다."""
    r1 = balanced_target_positions(20, num_choices=4, seed=1)
    r2 = balanced_target_positions(20, num_choices=4, seed=2)
    assert r1 != r2


def test_num_choices_one() -> None:
    """num_choices=1이면 모든 위치가 0이어야 한다."""
    result = balanced_target_positions(5, num_choices=1, seed=0)
    assert result == [0, 0, 0, 0, 0]


# ── 경계값 계약: count<=0 관용 반환 ([] 보존) ───────────────────────────────


@pytest.mark.parametrize("count", [0, -1, -5, -100])
@pytest.mark.parametrize("num_choices", [1, 4, 5])
@pytest.mark.parametrize("seed", [0, 42, 999])
def test_nonpositive_count_returns_empty_like_examforge(
    count: int, num_choices: int, seed: int
) -> None:
    """count<=0이면 num_choices·seed와 무관하게 []를 반환한다(ExamForge 원본과 byte-identical)."""
    expected = _ref_ef_balanced(count, num_choices, seed)
    actual = balanced_target_positions(count, num_choices, seed)
    assert actual == expected == []


def test_nonpositive_count_empty_even_when_num_choices_invalid() -> None:
    """count<=0이면 num_choices<1이어도 [] 조기 반환한다(원본 early return 보존)."""
    assert balanced_target_positions(0, num_choices=0) == []
    assert balanced_target_positions(-3, num_choices=0) == []
    assert balanced_target_positions(-1, num_choices=-2) == []


# ── 예외: count>0 인데 num_choices<1 ───────────────────────────────────────


def test_positive_count_zero_num_choices_raises() -> None:
    """count>0·num_choices<1은 ValueError. 원본은 ZeroDivisionError(modulo by zero)를 던졌으며,
    둘 다 '정상값을 반환하지 않는다'는 점에서 일치한다."""
    with pytest.raises(ValueError):
        balanced_target_positions(5, num_choices=0)


def test_positive_count_negative_num_choices_raises() -> None:
    with pytest.raises(ValueError):
        balanced_target_positions(5, num_choices=-1)


def test_original_also_fails_on_positive_count_zero_num_choices() -> None:
    """원본(ExamForge·ChapterStudio)도 count>0·num_choices=0에서 예외를 던졌음을 명시 증명한다.

    - ExamForge 원본: num_choices 가드 없음 → ZeroDivisionError(modulo by zero)
    - ChapterStudio 원본: num_choices<1 가드 있음 → ValueError
    - 단일소스: ValueError
    셋 다 '정상값을 반환하지 않는다'는 점에서 일치한다(단일소스는 CS 원본과 동일한 ValueError).
    """
    with pytest.raises(ZeroDivisionError):
        _ref_ef_balanced(5, num_choices=0)
    with pytest.raises(ValueError):
        _ref_cs_balanced(5, num_choices=0)


# ── seed_from_key 기본 동작 ────────────────────────────────────────────────


def test_seed_empty_string_is_zero() -> None:
    assert seed_from_key("") == 0


def test_seed_nonzero_for_nonempty() -> None:
    assert seed_from_key("some_key") != 0


def test_seed_reproducible() -> None:
    """같은 키면 항상 같은 seed."""
    assert seed_from_key("abc") == seed_from_key("abc")


def test_seed_different_keys_different_seeds() -> None:
    assert seed_from_key("key_a") != seed_from_key("key_b")


# ── 실제 호출처 위임 확인 ──────────────────────────────────────────────────


def test_chapterstudio_quiz_balance_delegates_to_single_source() -> None:
    """ChapterStudio quiz_balance.balanced_target_positions가 단일 소스를 re-export하는지 확인."""
    from app.modules.ChapterStudio_V1.postprocess.quiz_balance import (
        balanced_target_positions as cs_btp,
    )
    expected = balanced_target_positions(10, num_choices=4, seed=42)
    assert cs_btp(10, num_choices=4, seed=42) == expected


def test_examforge_concept_blueprint_delegates_to_single_source() -> None:
    """ExamForge concept_blueprint._balanced_target_positions가 단일 소스에 위임하는지 확인."""
    from app.modules.ExamForge_V1.pipeline.nodes.concept_blueprint import (
        _balanced_target_positions as ef_btp,
    )
    expected = balanced_target_positions(10, num_choices=4, seed=42)
    assert ef_btp(10, num_choices=4, seed=42) == expected
