"""SlotValidator 단위 테스트.

검사 항목:
  (a) exact-count + full index-set
  (b) per-slot constraint (min/max chars, required markers, choices 개수, enum 일치)
"""
from __future__ import annotations

import pytest

from app.core.planfirst.blueprint import GenBlueprint, GenSlot, SlotConstraints
from app.core.planfirst.validate import SlotValidator, SlotViolation


def _slot(slot_id: str, **constraint_kwargs: object) -> GenSlot:
    return GenSlot(
        slot_id=slot_id,
        kind="slide",
        fixed_fields={"slide_idx": int(slot_id) if slot_id.isdigit() else 0},
        ai_fields=("narration",),
        constraints=SlotConstraints(**constraint_kwargs),
    )


def _bp(*slot_ids: str) -> GenBlueprint:
    return GenBlueprint(slots=[_slot(sid) for sid in slot_ids])


validator = SlotValidator()


# ── count + index-set 검사 ─────────────────────────────────────────────────


class TestCountAndIndexSet:
    def test_exact_match_no_violations(self) -> None:
        bp = _bp("0", "1", "2")
        violations = validator.validate_count_and_index_set(bp, {"0", "1", "2"})
        assert violations == []

    def test_missing_slot(self) -> None:
        bp = _bp("0", "1", "2")
        violations = validator.validate_count_and_index_set(bp, {"0", "1"})
        checks = {v.check for v in violations}
        assert "index_set" in checks
        missing = [v for v in violations if v.slot_id == "2"]
        assert missing

    def test_extra_slot(self) -> None:
        bp = _bp("0", "1")
        violations = validator.validate_count_and_index_set(bp, {"0", "1", "99"})
        extra = [v for v in violations if v.slot_id == "99"]
        assert extra

    def test_count_mismatch_adds_violation(self) -> None:
        bp = _bp("0", "1", "2")
        violations = validator.validate_count_and_index_set(bp, {"0", "1"})
        count_viols = [v for v in violations if v.check == "count"]
        assert count_viols

    def test_empty_blueprint_empty_filled_ok(self) -> None:
        bp = GenBlueprint(slots=[])
        violations = validator.validate_count_and_index_set(bp, set())
        assert violations == []


# ── per-slot constraint 검사 ──────────────────────────────────────────────


class TestSlotConstraints:
    def test_no_constraints_no_violations(self) -> None:
        slot = _slot("0")
        violations = validator.validate_slot_constraints(slot, {"narration": "안녕하세요"})
        assert violations == []

    def test_min_chars_pass(self) -> None:
        slot = _slot("0", min_chars=5)
        violations = validator.validate_slot_constraints(slot, {"narration": "열 글자 이상 내레이션 텍스트"})
        assert violations == []

    def test_min_chars_fail(self) -> None:
        slot = _slot("0", min_chars=100)
        violations = validator.validate_slot_constraints(slot, {"narration": "짧음"})
        assert any(v.check == "chars" for v in violations)

    def test_max_chars_pass(self) -> None:
        slot = _slot("0", max_chars=10)
        violations = validator.validate_slot_constraints(slot, {"narration": "짧다"})
        assert violations == []

    def test_max_chars_fail(self) -> None:
        slot = _slot("0", max_chars=3)
        violations = validator.validate_slot_constraints(slot, {"narration": "이것은 너무 긴 내레이션이다"})
        assert any(v.check == "chars" for v in violations)

    def test_required_marker_present(self) -> None:
        slot = _slot("0", required_markers=("##REQUIRED##",))
        violations = validator.validate_slot_constraints(
            slot, {"narration": "앞부분 ##REQUIRED## 뒷부분"}
        )
        assert violations == []

    def test_required_marker_missing(self) -> None:
        slot = _slot("0", required_markers=("##REQUIRED##",))
        violations = validator.validate_slot_constraints(slot, {"narration": "마커 없음"})
        assert any(v.check == "markers" for v in violations)

    def test_exact_choices_pass(self) -> None:
        slot = _slot("0", exact_choices=4)
        ai_output = {"options": ["a", "b", "c", "d"]}
        violations = validator.validate_slot_constraints(slot, ai_output)
        assert violations == []

    def test_exact_choices_fail(self) -> None:
        slot = _slot("0", exact_choices=4)
        ai_output = {"options": ["a", "b", "c"]}
        violations = validator.validate_slot_constraints(slot, ai_output)
        assert any(v.check == "choices" for v in violations)

    def test_allowed_enum_pass(self) -> None:
        slot = _slot("0", allowed_enum=frozenset({"concept_map", "step_flow"}))
        ai_output = {"type": "concept_map"}
        violations = validator.validate_slot_constraints(slot, ai_output)
        assert violations == []

    def test_allowed_enum_fail(self) -> None:
        slot = _slot("0", allowed_enum=frozenset({"concept_map", "step_flow"}))
        ai_output = {"type": "unknown_type"}
        violations = validator.validate_slot_constraints(slot, ai_output)
        assert any(v.check == "enum" for v in violations)

    def test_allowed_enum_none_skips_check(self) -> None:
        slot = _slot("0")  # allowed_enum=None
        ai_output = {"type": "anything_goes"}
        violations = validator.validate_slot_constraints(slot, ai_output)
        assert not any(v.check == "enum" for v in violations)


# ── SlotViolation 구조 ─────────────────────────────────────────────────────


def test_violation_has_required_fields() -> None:
    v = SlotViolation(slot_id="3", check="count", message="테스트 메시지")
    assert v.slot_id == "3"
    assert v.check == "count"
    assert "테스트" in v.message
