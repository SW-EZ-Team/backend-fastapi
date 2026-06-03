"""실경로 plan 강제 통합 테스트 (dead code 재발 차단).

단위 주입 테스트(parse_slides(ai, plan))가 아니라 generate_lesson_parallel을 mock connector로
실제 호출해, mock이 plan.visual_type과 다른 type을 반환할 때 최종 payload의 visual.type이
plan 값으로 강제됐는지 검증한다. 이 테스트는 P0-1 dead code(slide_plan 미전달)를 잡는다.

검증:
    - drift: plan=number_line인데 AI가 concept_map 반환 → 최종 visual.type == number_line
    - title 재라벨: AI가 '챕터명 3' 형태 제목 반환 → 최종 title이 재라벨됨
    - 직렬/역직렬 왕복: prepare_context_node가 채운 slide_outline이 parse_slides에 실제 도달
AI 실호출 없음.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.pipeline.nodes.context_node import prepare_context_node
from app.modules.ChapterStudio_V1.pipeline.parallel_generate import generate_lesson_parallel
from app.modules.ChapterStudio_V1.pipeline.slide_plan import build_slide_plan
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState

_SLIDE_COUNT = 10

_VOICE_TEXT = (
    "자, 이번 화면에서는 핵심 개념을 직관부터 차근차근 설명하고, 실수하기 쉬운 경계 조건을 "
    "작은 예시로 직접 짚어 본 뒤 미니 연습으로 자연스럽게 마무리하겠습니다. 한 번 더 정리하면, "
    "왜 이렇게 동작하는지 이유까지 함께 이해하는 것이 중요합니다. 천천히 따라와 주세요."
)
_QUIZ_EXPLANATION = (
    "정답은 A이며 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다. "
    "경계 조건을 놓치는 약점과 직접 연결되므로 종료 조건을 끝까지 따지는 습관이 필요합니다."
)


def _state_with_real_plan() -> ChapterStudioState:
    """prepare_context_node로 실제 slide_outline(visual_type 포함)을 채운 state를 만든다.

    이렇게 해야 직렬(context_node)→역직렬(parse_slides) 왕복이 실경로 그대로 검증된다.
    """
    base: ChapterStudioState = {
        "topic": "정수의 크기 비교",
        "chapter_brief": "수직선에서 음수와 양수의 크기를 비교하는 단원",
        "learning_goal": "음수끼리 크기 비교를 수직선으로 판단",
        "slide_count": _SLIDE_COUNT,
        "requested_template": "math_reasoning",
    }
    enriched = prepare_context_node(base)
    return {**base, **enriched}


def _plan_visual_types() -> list[str]:
    """state가 들고 갈 plan의 슬롯별 visual_type(기대값)을 결정적으로 구한다."""
    plans = build_slide_plan("math_reasoning", _SLIDE_COUNT)
    return [p.visual_type for p in plans]


@pytest.mark.anyio
async def test_drift_visual_type_forced_to_plan_in_real_path() -> None:
    """AI가 plan과 다른 visual.type을 반환해도 최종 payload는 plan 값으로 강제된다.

    이 테스트가 통과하려면 generate_lesson_parallel이 slide_plan을 parse_slides에 실제로
    전달해야 한다(P0-1). 전달 안 되면 AI의 drift type(concept_map)이 그대로 살아남아 실패한다.
    """
    state = _state_with_real_plan()
    expected_types = _plan_visual_types()
    # mock connector는 모든 슬롯에 concept_map(=거의 모든 슬롯에서 drift)을 반환한다.
    connector = _DriftConnector(forced_visual_type="concept_map")

    payload = await generate_lesson_parallel(connector, state, _SLIDE_COUNT)

    # 최종 payload의 각 슬롯 visual.type이 plan 값으로 강제됐는지 검증.
    by_idx = {s.slide_idx: s for s in payload.slides}
    drift_corrected = 0
    for idx, expected in enumerate(expected_types):
        actual = by_idx[idx].visual.get("type")
        assert actual == expected, (
            f"slide_idx={idx}: plan visual_type={expected} 강제 실패, 실제={actual} "
            "(slide_plan이 parse_slides에 전달 안 됐을 가능성 — P0-1 dead code)"
        )
        if expected != "concept_map":
            drift_corrected += 1
    # 적어도 일부 슬롯은 concept_map이 아니므로 실제 drift 교정이 일어났음을 증명한다.
    assert drift_corrected > 0, "drift 교정이 한 건도 없으면 테스트가 무의미하다."


@pytest.mark.anyio
async def test_chapter_number_title_relabeled_in_real_path() -> None:
    """AI가 '챕터명+번호' 제목을 반환하면 실경로에서 결정적 재라벨된다."""
    state = _state_with_real_plan()
    # 모든 슬롯에 '수직선과 정수의 위치 N' 형태(챕터명+번호) 제목을 반환한다.
    connector = _DriftConnector(forced_visual_type="example_box", chapter_number_title=True)

    payload = await generate_lesson_parallel(connector, state, _SLIDE_COUNT)

    # 제목이 '... 3' 형태로 남아 있으면 재라벨 실패.
    for slide in payload.slides:
        assert not _is_chapter_number_title(slide.title), (
            f"slide_idx={slide.slide_idx}: 챕터명+번호 제목 '{slide.title}' 재라벨 실패"
        )


@pytest.mark.anyio
async def test_no_drift_passes_unchanged_in_real_path() -> None:
    """AI가 plan과 동일한 visual.type을 반환하면 그대로 보존된다(과잉 교정 없음)."""
    state = _state_with_real_plan()
    expected_types = _plan_visual_types()
    # plan 그대로 반환하는 정직한 커넥터.
    connector = _PlanFaithfulConnector(expected_types)

    payload = await generate_lesson_parallel(connector, state, _SLIDE_COUNT)

    by_idx = {s.slide_idx: s for s in payload.slides}
    for idx, expected in enumerate(expected_types):
        assert by_idx[idx].visual.get("type") == expected


def _is_chapter_number_title(title: str) -> bool:
    # 단일 진실 소스(title_rules)로 판정해 정규식 중복을 피한다.
    from app.modules.ChapterStudio_V1.postprocess.title_rules import is_chapter_number_title
    return is_chapter_number_title(title)


# ── mock 커넥터들 ────────────────────────────────────────────────────


class _BaseComponentConnector:
    """slides 외 컴포넌트를 정상 응답하는 batch 지원 fake 커넥터 베이스."""

    name = "drift_fake"

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.calls_by_schema: dict[str, int] = {}

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        schema = str(req.extra.get("schema", ""))
        self.calls_by_schema[schema] = self.calls_by_schema.get(schema, 0) + 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.005)
            return _resp(self._body(req, schema))
        finally:
            self.active -= 1

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return feature in {"batch", "long_context", "shutdown"}

    def _body(self, req: ChapterAIRequest, schema: str) -> str:
        if schema == "slides":
            return self._slides_body(req)
        if schema == "quizzes":
            return json.dumps({"quizzes": [_quiz(i) for i in range(_SLIDE_COUNT)]}, ensure_ascii=False)
        if schema == "note":
            return json.dumps({"note_blocks": [_note(i) for i in range(4)]}, ensure_ascii=False)
        if schema == "assignment":
            return json.dumps({"assignment": _assignment()}, ensure_ascii=False)
        if schema == "voice_script":
            slide_idx = int(req.extra.get("slide_idx", 0))
            return json.dumps({"slide_idx": slide_idx, "script_text": _VOICE_TEXT}, ensure_ascii=False)
        raise AssertionError(f"예상치 못한 schema: {schema}")

    def _slides_body(self, req: ChapterAIRequest) -> str:  # pragma: no cover - 서브클래스가 구현
        raise NotImplementedError


class _DriftConnector(_BaseComponentConnector):
    """slides에서 plan과 다른 visual.type(또는 챕터명+번호 제목)을 반환하는 커넥터."""

    def __init__(self, forced_visual_type: str, chapter_number_title: bool = False) -> None:
        super().__init__()
        self._forced_visual_type = forced_visual_type
        self._chapter_number_title = chapter_number_title

    def _slides_body(self, req: ChapterAIRequest) -> str:
        slides = []
        for i in range(_SLIDE_COUNT):
            title = f"수직선과 정수의 위치 {i}" if self._chapter_number_title else f"개념 설명 슬라이드"
            slides.append(_drift_slide(i, self._forced_visual_type, title))
        return json.dumps({"slides": slides}, ensure_ascii=False)


class _PlanFaithfulConnector(_BaseComponentConnector):
    """slides에서 plan visual_type을 정직하게 반환하는 커넥터(과잉 교정 검출용)."""

    def __init__(self, plan_types: list[str]) -> None:
        super().__init__()
        self._plan_types = plan_types

    def _slides_body(self, req: ChapterAIRequest) -> str:
        slides = [
            _drift_slide(i, self._plan_types[i], "개념 설명 슬라이드")
            for i in range(_SLIDE_COUNT)
        ]
        return json.dumps({"slides": slides}, ensure_ascii=False)


def _resp(text: str) -> ChapterAIResponse:
    return ChapterAIResponse(text=text, model="fake", input_tokens=1, output_tokens=1, finish_reason="stop")


def _drift_slide(idx: int, visual_type: str, title: str) -> dict[str, object]:
    """visual.type을 지정 값으로 반환하는 구조화 visual 슬라이드 항목을 만든다."""
    return {
        "slide_idx": idx,
        "title": title,
        "category": "text",
        "narration": (
            "음수와 양수의 위치를 수직선에서 직접 확인합니다. 오른쪽에 있을수록 큰 수라는 "
            "기준으로 부호가 붙은 수의 크기를 안정적으로 판단할 수 있습니다."
        ),
        "visual": {
            "type": visual_type,
            "data": {"title": "핵심", "value": "기준", "caption": "수직선 위치로 판단"},
        },
        "checkpoint": "이 기준을 말로 설명할 수 있는가?",
    }


def _quiz(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "question": f"슬라이드 {idx} 질문입니다.",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "이해",
        "explanation": _QUIZ_EXPLANATION,
    }


def _note(idx: int) -> dict[str, object]:
    return {
        "heading": f"핵심 {idx}",
        "bullets": [
            "핵심 개념을 한 문장으로 다시 정리하면서 왜 중요한지 배경까지 복습합니다.",
            "실수하기 쉬운 경계 조건을 작은 예시로 직접 점검하는 습관을 만듭니다.",
            "오해하기 쉬운 부분을 반례와 함께 짚어 정확한 판단 기준을 세웁니다.",
        ],
    }


def _assignment() -> dict[str, object]:
    return {
        "title": "실습 과제",
        "assignment_format": "문제풀이+근거 표시",
        "expected_minutes": 30,
        "steps": ["핵심 개념을 직접 적용해 봅니다.", "결과를 근거와 함께 정리합니다."],
        "rubric": ["근거가 명확한가", "예외 처리가 정확한가"],
    }
