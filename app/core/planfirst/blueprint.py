"""plan-first 공통 슬롯 계약 데이터클래스.

GenSlot은 코드가 결정하는 고정 필드와 AI가 채울 수 있는 필드의 경계를 명시한다.
GenBlueprint는 슬롯 목록을 순서 보장 컨테이너로 묶는다.

ChapterStudio의 SlidePlan·slide_outline과 ExamForge의 question_blueprint를
개념적으로 일반화한 상위 계약이다. 기존 타입을 대체하지 않는다.

대응 관계:
  ChapterStudio  │ ExamForge          │ 이 계약
  ─────────────────────────────────────────────
  SlidePlan      │ 블루프린트 슬롯 dict │ GenSlot
  SlidePlan.list │ question_blueprint  │ GenBlueprint
  visual_type 등 │ template_id 등     │ fixed_fields
  narration 등   │ stem/choices 등    │ ai_fields
  narration_len  │ num_choices 등     │ constraints
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SlotConstraints:
    """AI가 채울 필드에 대한 결정적 제약 집합.

    모든 필드는 선택적이며, 사용하지 않는 파이프라인에서는 None으로 둔다.

    Attributes:
        min_chars: 텍스트 필드 최소 글자 수.
        max_chars: 텍스트 필드 최대 글자 수.
        required_markers: 결과물에 반드시 포함돼야 하는 마커 문자열 목록.
        exact_choices: 객관식 보기 수(None이면 제약 없음).
        sentence_count_range: (min, max) 문장 수 범위.
        allowed_enum: 열거형 필드에 허용되는 값 집합(예: visual_type 허용 목록).
    """
    min_chars: int | None = None
    max_chars: int | None = None
    # frozen dataclass라 빈 튜플 리터럴은 불변·공유 안전하므로 default로 직접 둔다.
    required_markers: tuple[str, ...] = ()
    exact_choices: int | None = None
    sentence_count_range: tuple[int, int] | None = None
    allowed_enum: frozenset[str] | None = None


@dataclass(frozen=True)
class GenSlot:
    """슬롯 1개의 결정적 계약 — AI 호출 전 코드가 완전 확정한다.

    Attributes:
        slot_id: 슬롯 식별자(슬라이드 인덱스, 문항 번호 등).
        kind: 슬롯 종류('slide'·'question'·'voice' 등 파이프라인별 정의).
        fixed_fields: 코드가 결정한 고정 필드(slide_idx/category/difficulty/
                      template_id/answer_position 등). AI가 변경 불가.
        ai_fields: AI가 채울 수 있는 필드 이름 튜플(예: ('narration', 'visual_data')).
        constraints: ai_fields에 적용되는 결정적 제약.
    """
    slot_id: str
    kind: str
    fixed_fields: dict[str, object]
    ai_fields: tuple[str, ...]
    constraints: SlotConstraints = field(default_factory=SlotConstraints)


@dataclass
class GenBlueprint:
    """GenSlot의 순서 보장 목록 — 생성 파이프라인이 소비하는 최소 계약.

    슬롯 인덱스 완전집합(0..N-1)과 slot_id 유일성을 생성 시점에 검증한다.
    """
    slots: list[GenSlot]

    def __post_init__(self) -> None:
        """슬롯 목록의 무결성을 초기화 시점에 검증한다."""
        ids = [s.slot_id for s in self.slots]
        if len(ids) != len(set(ids)):
            raise ValueError("GenBlueprint: slot_id 중복이 있다.")

    def __len__(self) -> int:
        return len(self.slots)

    def __iter__(self) -> Iterator[GenSlot]:
        return iter(self.slots)

    def __getitem__(self, index: int) -> GenSlot:
        return self.slots[index]


__all__ = ["SlotConstraints", "GenSlot", "GenBlueprint"]
