"""GenBlueprint / GenSlot / SlotConstraints 단위 테스트."""
from __future__ import annotations

import pytest

from app.core.planfirst.blueprint import GenBlueprint, GenSlot, SlotConstraints


def _make_slot(slot_id: str, kind: str = "slide") -> GenSlot:
    return GenSlot(
        slot_id=slot_id,
        kind=kind,
        fixed_fields={"slide_idx": int(slot_id), "category": "text"},
        ai_fields=("narration", "title"),
        constraints=SlotConstraints(min_chars=100, max_chars=400),
    )


class TestGenSlot:
    def test_frozen_immutable(self) -> None:
        """frozen=True dataclass는 일반 속성 대입을 막는다.

        setattr(동적 호출)로 대입해 정적 타입 검사를 우회하지 않고 런타임 FrozenInstanceError를 확인한다.
        """
        slot = _make_slot("0")
        with pytest.raises(Exception):
            setattr(slot, "slot_id", "99")

    def test_fields_accessible(self) -> None:
        slot = _make_slot("5", kind="question")
        assert slot.slot_id == "5"
        assert slot.kind == "question"
        assert "narration" in slot.ai_fields

    def test_default_constraints(self) -> None:
        slot = GenSlot(
            slot_id="x",
            kind="voice",
            fixed_fields={},
            ai_fields=(),
        )
        assert slot.constraints.min_chars is None
        assert slot.constraints.exact_choices is None


class TestGenBlueprint:
    def test_empty_blueprint(self) -> None:
        bp = GenBlueprint(slots=[])
        assert len(bp) == 0

    def test_length_and_iter(self) -> None:
        slots = [_make_slot(str(i)) for i in range(5)]
        bp = GenBlueprint(slots=slots)
        assert len(bp) == 5
        assert list(bp) == slots

    def test_getitem(self) -> None:
        slots = [_make_slot(str(i)) for i in range(3)]
        bp = GenBlueprint(slots=slots)
        assert bp[0].slot_id == "0"
        assert bp[2].slot_id == "2"

    def test_duplicate_slot_id_raises(self) -> None:
        with pytest.raises(ValueError, match="slot_id 중복"):
            GenBlueprint(slots=[_make_slot("1"), _make_slot("1")])

    def test_unique_slot_ids_accepted(self) -> None:
        bp = GenBlueprint(slots=[_make_slot("0"), _make_slot("1"), _make_slot("2")])
        assert len(bp) == 3


class TestSlotConstraints:
    def test_defaults_all_none(self) -> None:
        c = SlotConstraints()
        assert c.min_chars is None
        assert c.max_chars is None
        assert c.exact_choices is None
        assert c.sentence_count_range is None
        assert c.allowed_enum is None
        assert c.required_markers == ()

    def test_allowed_enum_frozenset(self) -> None:
        c = SlotConstraints(allowed_enum=frozenset({"a", "b", "c"}))
        # None 가능성을 먼저 좁혀 멤버십 검사를 타입 안전하게 한다(type:ignore 불필요).
        assert c.allowed_enum is not None
        enum = c.allowed_enum
        assert "a" in enum
        assert "z" not in enum
