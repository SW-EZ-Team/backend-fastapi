"""슬라이드 플랜 — AI 호출 전 결정적으로 확정되는 슬롯별 계약.

plan-first over-reach 제거의 핵심 모듈이다.
- SlidePlan : 슬롯 1개의 결정적 계약(visual_type 포함)
- build_slide_plan : template_key + slide_count → 길이 N인 SlidePlan 목록 결정적 생성

AI는 각 슬롯의 텍스트(title/narration/visual.data)만 채운다.
visual.type·category·role·must_have·개수·인덱스는 코드가 결정한다.

시퀀스 원칙:
  도입 1개 → 본론(프레임 0·1·2·3 순환) → 마무리 1개(점검)
  한 강의에서 최소 3종 visual_type 분포가 자동 보장된다.

공개 API:
  - SlidePlan
  - build_slide_plan(template_key, slide_count)
"""
from __future__ import annotations

from dataclasses import dataclass

from app.modules.ChapterStudio_V1.app.study_templates import get_template
from app.modules.ChapterStudio_V1.app.template_types import SlideFrame


@dataclass(frozen=True)
class SlidePlan:
    """슬롯 1개의 결정적 계약 — AI 호출 전 코드가 완전 확정한다."""

    slide_idx: int              # 0-based 인덱스 (0..N-1 완전집합 보장)
    category: str               # SlideCategory 값
    role: str                   # 슬라이드 역할 문자열
    must_have: tuple[str, ...]  # 반드시 포함할 개념 목록
    visual_type: str            # AI가 생성해야 할 visual.type 단일값 (고정)
    title_constraint: str       # 제목 제약 설명 (6~16자 명사구, 챕터명+번호 금지)
    narration_len: tuple[int, int]  # (min, max) 내레이션 글자 수


# 기본 제목 제약 설명 — 모든 슬롯에 공통 적용
_TITLE_CONSTRAINT = "6~16자 명사구만, 챕터명+번호 형태 금지"

# 내레이션 길이 범위 (min, max) — 슬롯 역할별 차등 적용
_NARRATION_RANGES: dict[str, tuple[int, int]] = {
    "도입": (200, 280),
    "확장 질문": (200, 300),
    "강의 끝 점검": (200, 300),
}
_NARRATION_DEFAULT: tuple[int, int] = (200, 360)

# visual_type 폴백 — SlideFrame.visual_type이 None인 경우 category별 기본값
_CATEGORY_FALLBACK_VISUAL: dict[str, str] = {
    "text": "example_box",
    "diagram": "concept_map",
    "code": "example_box",
    "math": "step_flow",
    "chart": "comparison-table",
    "interactive": "example_box",
}


def build_slide_plan(template_key: str, slide_count: int) -> list[SlidePlan]:
    """결정적 N-슬라이드 SlidePlan 목록을 생성한다(AI 미관여).

    시퀀스:
      - slide 0       : 템플릿 frame0(도입·개념 정리 역할)
      - slide 1..N-2  : 중간 프레임 frame1·2·3 순환 (본론)
      - slide N-1     : 템플릿 frame4(강의 끝 점검)

    slide_count=1 예외: frame0 하나만.
    slide_count=2 예외: frame0 + frame4.
    slide_count=3·4 예외: frame0 + (frame1·2·3 일부) + frame4 — 가용 슬롯이 적어
      5개 프레임을 모두 담지 못하므로 3종 분포가 보장되지 않을 수 있다(아래 참고).

    최소 3종 visual_type 보장 (정직한 범위):
      각 템플릿의 5개 프레임은 항상 3종 이상의 서로 다른 visual_type을 가진다
      (catalog _t/_FRAME_TAIL_VISUAL가 보장, test_template_frames_have_3plus_types가 강제).
      따라서 N≥5이면 frame0~4가 모두 시퀀스에 등장하므로 3종 분포가 결정적으로 보장된다.
      N=3·4(비프로덕션 소형 케이스 — 운영 slide_count는 slide_count_from_minutes로 항상
      10~15)에서는 5개 프레임 전체를 담지 못해 2종이 될 수 있다(보장 안 함).
    """
    if slide_count < 1:
        raise ValueError(f"slide_count는 1 이상이어야 한다. 받은 값: {slide_count}")
    template = get_template(template_key)
    frames = template.frames  # tuple[SlideFrame, ...] 길이 5

    if slide_count == 1:
        return [_slot(0, frames[0])]
    if slide_count == 2:
        return [_slot(0, frames[0]), _slot(1, frames[4])]

    # 본론 슬롯: 1..N-2 → 중간 프레임 frame1·2·3 순환.
    # frame0(첫 슬롯)·frame4(마지막 슬롯)와 분리해 N≥5에서 5개 프레임이 모두 등장하게 한다.
    # → 5개 프레임이 3종 이상 type을 보장하므로 N≥5 3종 분포가 결정적으로 성립한다.
    middle_frames = frames[1:4]  # frame1, frame2, frame3
    plans: list[SlidePlan] = [_slot(0, frames[0])]
    body_count = slide_count - 2
    for i in range(body_count):
        frame = middle_frames[i % len(middle_frames)]
        plans.append(_slot(i + 1, frame))
    plans.append(_slot(slide_count - 1, frames[4]))
    return plans


def _slot(slide_idx: int, frame: SlideFrame) -> SlidePlan:
    """SlideFrame 하나를 SlidePlan 슬롯으로 변환한다."""
    visual_type = frame.visual_type or _CATEGORY_FALLBACK_VISUAL.get(frame.category, "example_box")
    narration_len = _NARRATION_RANGES.get(frame.role, _NARRATION_DEFAULT)
    return SlidePlan(
        slide_idx=slide_idx,
        category=frame.category,
        role=frame.role,
        must_have=frame.must_have,
        visual_type=visual_type,
        title_constraint=_TITLE_CONSTRAINT,
        narration_len=narration_len,
    )


def serialize_slide_plan(plans: list[SlidePlan]) -> list[dict[str, object]]:
    """SlidePlan 목록을 StateRecord 형식(dict 행)으로 직렬화한다(하위호환·왕복 무결).

    state["slide_outline"]에 저장되는 형식과 parse_slides가 slide_plan으로 소비하는 형식의
    단일 진실 소스다. slide_idx·visual_type·must_have를 보존해 역직렬화 시 대조가 가능하다.
    """
    rows: list[dict[str, object]] = []
    for p in plans:
        rows.append(
            {
                "slide_idx": p.slide_idx,
                "category": p.category,
                "role": p.role,
                "must_have": list(p.must_have),
                "visual_type": p.visual_type,
                "title_constraint": p.title_constraint,
                "narration_len": p.narration_len,
            }
        )
    return rows


__all__ = ["SlidePlan", "build_slide_plan", "serialize_slide_plan"]
