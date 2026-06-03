"""plan-first 공통 슬롯 검증 순수함수.

ChapterStudio의 _validate_indices 와 ExamForge의 _validate_question_count/
_validate_concept_key_uniqueness가 각각 구현하는 슬롯 count·index 완전집합 검사와
per-slot 제약 검사를 일반화한 순수함수 집합이다.

기존 파이프라인 검증 경로를 재작성하지 않는다. 새 파이프라인 또는 기존 모듈이
이 검증기를 선택적으로 사용할 수 있게 하되 강제 교체하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.planfirst.blueprint import GenBlueprint, GenSlot, SlotConstraints


@dataclass
class SlotViolation:
    """검증 실패 1건을 표현한다."""
    slot_id: str
    check: str       # 'count' | 'index_set' | 'chars' | 'markers' | 'choices' | 'enum'
    message: str


class SlotValidator:
    """GenBlueprint 단위의 결정적 슬롯 검증기.

    (a) exact-count + full index-set 체크
    (b) per-slot constraint (min/max chars, required markers, choices 개수, enum 일치)

    기존 모듈의 _validate_indices (ChapterStudio) 와 _validate_question_count (ExamForge) 가
    공통으로 수행하는 슬롯 1:1 채움 검사의 일반화 형태다.
    """

    def validate_count_and_index_set(
        self,
        blueprint: GenBlueprint,
        filled_slot_ids: set[str],
    ) -> list[SlotViolation]:
        """블루프린트 slot_id 집합과 실제 채워진 slot_id 집합을 비교한다.

        누락 슬롯과 초과 슬롯을 각각 violations로 반환한다.
        """
        plan_ids = {s.slot_id for s in blueprint.slots}
        missing = plan_ids - filled_slot_ids
        extra = filled_slot_ids - plan_ids
        violations: list[SlotViolation] = []
        for sid in sorted(missing):
            violations.append(SlotViolation(
                slot_id=sid,
                check="index_set",
                message=f"슬롯 {sid}가 채워지지 않았다.",
            ))
        for sid in sorted(extra):
            violations.append(SlotViolation(
                slot_id=sid,
                check="index_set",
                message=f"슬롯 {sid}는 블루프린트에 없는 초과 슬롯이다.",
            ))
        if len(blueprint.slots) != len(filled_slot_ids):
            violations.append(SlotViolation(
                slot_id="__blueprint__",
                check="count",
                message=(
                    f"슬롯 수 불일치: 계획={len(blueprint.slots)}, "
                    f"실제={len(filled_slot_ids)}"
                ),
            ))
        return violations

    def validate_slot_constraints(
        self,
        slot: GenSlot,
        ai_output: dict[str, object],
    ) -> list[SlotViolation]:
        """단일 슬롯의 ai_output이 SlotConstraints를 만족하는지 검사한다.

        ai_output의 각 필드를 제약 조건에 대조한다.
        """
        c = slot.constraints
        violations: list[SlotViolation] = []
        # 텍스트 필드 전체를 이어붙여 글자 수 측정
        text_value = " ".join(
            str(ai_output.get(f, ""))
            for f in slot.ai_fields
            if isinstance(ai_output.get(f), str)
        )
        violations.extend(self._check_chars(slot.slot_id, text_value, c))
        violations.extend(self._check_markers(slot.slot_id, text_value, c))
        violations.extend(self._check_choices(slot.slot_id, ai_output, c))
        violations.extend(self._check_enum(slot.slot_id, ai_output, slot.fixed_fields, c))
        return violations

    # ── 내부 검사 메서드 ──────────────────────────────────────────────────────

    @staticmethod
    def _check_chars(
        slot_id: str,
        text: str,
        c: SlotConstraints,
    ) -> list[SlotViolation]:
        """min/max chars 제약을 검사한다."""
        violations: list[SlotViolation] = []
        length = len(text)
        if c.min_chars is not None and length < c.min_chars:
            violations.append(SlotViolation(
                slot_id=slot_id,
                check="chars",
                message=f"텍스트 길이 {length}자가 최소 {c.min_chars}자 미달이다.",
            ))
        if c.max_chars is not None and length > c.max_chars:
            violations.append(SlotViolation(
                slot_id=slot_id,
                check="chars",
                message=f"텍스트 길이 {length}자가 최대 {c.max_chars}자 초과다.",
            ))
        return violations

    @staticmethod
    def _check_markers(
        slot_id: str,
        text: str,
        c: SlotConstraints,
    ) -> list[SlotViolation]:
        """required_markers 제약을 검사한다."""
        violations: list[SlotViolation] = []
        for marker in c.required_markers:
            if marker not in text:
                violations.append(SlotViolation(
                    slot_id=slot_id,
                    check="markers",
                    message=f"필수 마커 '{marker}'가 출력에 없다.",
                ))
        return violations

    @staticmethod
    def _check_choices(
        slot_id: str,
        ai_output: dict[str, object],
        c: SlotConstraints,
    ) -> list[SlotViolation]:
        """exact_choices(보기 수) 제약을 검사한다."""
        if c.exact_choices is None:
            return []
        # 'options' 또는 'choices' 필드를 보기 목록으로 인식한다
        choices = ai_output.get("options") or ai_output.get("choices") or []
        if not isinstance(choices, (list, tuple)):
            return []
        actual = len(choices)
        if actual != c.exact_choices:
            return [SlotViolation(
                slot_id=slot_id,
                check="choices",
                message=f"보기 수 {actual}개가 요구 {c.exact_choices}개와 다르다.",
            )]
        return []

    @staticmethod
    def _check_enum(
        slot_id: str,
        ai_output: dict[str, object],
        fixed_fields: dict[str, object],
        c: SlotConstraints,
    ) -> list[SlotViolation]:
        """allowed_enum 제약을 검사한다.

        fixed_fields의 'kind' 또는 ai_output의 'type' 필드를 확인한다.
        """
        if c.allowed_enum is None:
            return []
        value = str(
            ai_output.get("type")
            or ai_output.get("visual_type")
            or fixed_fields.get("kind", "")
        )
        if value and value not in c.allowed_enum:
            return [SlotViolation(
                slot_id=slot_id,
                check="enum",
                message=f"값 '{value}'이 허용 enum {sorted(c.allowed_enum)} 밖이다.",
            )]
        return []


__all__ = ["SlotValidator", "SlotViolation"]
