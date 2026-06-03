"""app/core/planfirst: plan-first 공통 계약 패키지.

모든 생성 파이프라인(커리큘럼·슬라이드·음성·모의고사)에 공통으로 적용되는
plan-first 레이어의 계약, 검증, 위치 배정, 폴백 등록 인터페이스를 제공한다.

기존 파이프라인 동작을 재작성하지 않고, 공통 개념의 상위 계약만 선언한다.
"""
from app.core.planfirst.blueprint import GenBlueprint, GenSlot, SlotConstraints
from app.core.planfirst.validate import SlotValidator
from app.core.planfirst.fallback import FallbackRegistry
from app.core.planfirst.positions import (
    balanced_target_positions,
    seed_from_key,
)

__all__ = [
    "GenBlueprint",
    "GenSlot",
    "SlotConstraints",
    "SlotValidator",
    "FallbackRegistry",
    "balanced_target_positions",
    "seed_from_key",
]
