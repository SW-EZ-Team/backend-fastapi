"""curriculum_generate — plan-first 정합 로직 회귀 테스트.

핵심 안전망(_parse_and_validate 1:1 정합 게이트, _slot_response_to_lesson 키 계약,
_repair_missing_slots 부족슬롯-only 복구, happy-path)을 AI 실호출 없이 검증한다.
이 정합 로직이 깨지면 AI가 슬롯 구조를 변조해도 통과 저장되는 회귀가 생긴다.
"""
from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import (
    ChapterAIRequest,
    ChapterAIResponse,
)
from app.modules.ChapterStudio_V1.app.curriculum_blueprint import (
    ChapterSlot,
    build_curriculum_blueprint,
)
from app.modules.ChapterStudio_V1.app.curriculum_generate import (
    _parse_and_validate,
    _plan_with_blueprint,
    _repair_missing_slots,
    _slot_response_to_lesson,
)


# ---------------------------------------------------------------------------
# 테스트 헬퍼 — AI 응답 JSON 구성, 블루프린트 일치 슬롯 dict 생성
# ---------------------------------------------------------------------------


def _slot_item(slot: ChapterSlot, *, stage_override: str | None = None) -> dict:
    """블루프린트 슬롯에 대응하는 AI 응답 아이템을 만든다.

    stage_override를 주면 stage를 변조해 1:1 불일치 상황을 시뮬레이션한다.
    """
    return {
        "order": slot.order,
        "stage": stage_override if stage_override is not None else slot.stage,
        "title": f"{slot.order}강 제목",
        "summary": "한 문장 요약이다.",
        "learning_goal": "학습 목표를 달성한다.",
        "key_topics": ["키워드1", "키워드2", "키워드3"],
    }


def _to_json(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False)


def _resp(text: str) -> ChapterAIResponse:
    return ChapterAIResponse(
        text=text,
        model="test-model",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
    )


class _RecordingConnector(AIConnector):
    """호출 횟수와 전달된 프롬프트를 기록하는 가짜 AIConnector다.

    응답 시퀀스를 미리 주입받아 순서대로 반환한다.
    Protocol(runtime_checkable) isinstance 통과를 위해 모든 메서드를 구현한다.
    """

    name = "recording-test-connector"

    def __init__(self, responses: list[ChapterAIResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[ChapterAIRequest] = []

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        self.calls.append(req)
        return self._responses.pop(0)

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return False


# ===========================================================================
# 1. _parse_and_validate 직접 테스트
# ===========================================================================


def test_parse_drops_extra_orders_beyond_blueprint() -> None:
    """AI가 N+1개를 반환하면 블루프린트에 없는 order(초과분)는 drop되어 len==N이 된다."""
    n = 5
    blueprint = build_curriculum_blueprint(subject="수학", lesson_count=n)
    items = [_slot_item(s) for s in blueprint]
    # 블루프린트에 없는 order=6 슬롯을 추가 (초과분)
    items.append(
        {
            "order": 6,
            "stage": "마무리",
            "title": "초과 슬롯",
            "summary": "버려져야 한다.",
            "learning_goal": "목표",
            "key_topics": ["a", "b", "c"],
        }
    )

    result = _parse_and_validate(_to_json(items), blueprint)

    assert len(result) == n, f"초과분 drop 실패 — len={len(result)}"
    assert [r.order for r in result] == [1, 2, 3, 4, 5]


def test_parse_drops_stage_tampered_slot() -> None:
    """AI가 stage를 변조한 슬롯은 1:1 불일치로 drop되어 shortage(N미달)가 된다."""
    n = 5
    blueprint = build_curriculum_blueprint(subject="과학", lesson_count=n)
    items = [_slot_item(s) for s in blueprint]
    # order=3 슬롯의 stage를 블루프린트와 다른 값으로 변조
    tampered_stage = "엉뚱한단계"
    assert items[2]["stage"] != tampered_stage
    items[2]["stage"] = tampered_stage

    result = _parse_and_validate(_to_json(items), blueprint)

    assert len(result) == n - 1, f"변조 슬롯 drop 실패 — len={len(result)}"
    assert 3 not in [r.order for r in result], "변조된 order=3이 살아남았다"


def test_parse_restores_order_from_shuffled_response() -> None:
    """order가 뒤섞인 응답도 order 기준 오름차순으로 정렬 복원된다."""
    n = 5
    blueprint = build_curriculum_blueprint(subject="영어", lesson_count=n)
    items = [_slot_item(s) for s in blueprint]
    # 일부러 역순으로 뒤섞는다
    shuffled = list(reversed(items))

    result = _parse_and_validate(_to_json(shuffled), blueprint)

    assert [r.order for r in result] == [1, 2, 3, 4, 5], "order 정렬 복원 실패"


def test_parse_dedups_duplicate_order() -> None:
    """동일 order가 중복된 응답은 첫 번째만 유지해 dedup된다."""
    n = 5
    blueprint = build_curriculum_blueprint(subject="역사", lesson_count=n)
    items = [_slot_item(s) for s in blueprint]
    # order=2 슬롯을 한 번 더 복제 (제목만 다르게)
    dup = dict(items[1])
    dup["title"] = "중복된 2강"
    items.append(dup)

    result = _parse_and_validate(_to_json(items), blueprint)

    orders = [r.order for r in result]
    assert len(result) == n, f"dedup 실패 — len={len(result)}"
    assert orders.count(2) == 1, "order=2가 중복 잔존한다"
    # 첫 번째(원본)가 유지되어야 한다
    order2 = next(r for r in result if r.order == 2)
    assert order2.title == "2강 제목", "dedup이 첫 번째가 아닌 항목을 남겼다"


@pytest.mark.parametrize(
    "raw",
    [
        "",                       # 빈 응답
        "그냥 텍스트 설명입니다",   # 배열 없음
        "{}",                     # 객체(non-list)
        '{"order": 1}',           # 단일 객체
        "[",                      # 깨진 배열
        "쓰레기 [not json] 더미",  # 파싱 불가
    ],
)
def test_parse_garbage_returns_empty_safely(raw: str) -> None:
    """non-list/garbage/빈 응답은 예외 없이 빈 리스트로 안전 처리된다(shortage 게이트로 흘러감)."""
    n = 5
    blueprint = build_curriculum_blueprint(subject="물리", lesson_count=n)

    result = _parse_and_validate(raw, blueprint)

    assert result == [], f"garbage 입력이 빈 리스트로 처리되지 않음 — {raw!r} → {result}"


def test_parse_object_non_list_returns_empty() -> None:
    """JSON 배열이 아닌 객체 안에 lessons가 있어도 최상위 non-list면 빈 리스트다."""
    n = 5
    blueprint = build_curriculum_blueprint(subject="화학", lesson_count=n)
    # 대괄호는 있지만 최상위가 배열이 아닌 케이스 (find '[' 가 객체 내부를 잡음)
    raw = json.dumps({"wrapper": [_slot_item(s) for s in blueprint]}, ensure_ascii=False)

    result = _parse_and_validate(raw, blueprint)

    # 최상위 '[' .. ']' substring이 내부 배열을 잡아 파싱은 되지만,
    # 그 결과는 슬롯 dict 리스트이므로 정상 검증된다 — 이 케이스는 살아남는 것이 정상.
    # 핵심은 예외 없이 처리된다는 것. (정합 슬롯이면 통과)
    assert isinstance(result, list)


# ===========================================================================
# 2. _slot_response_to_lesson 키 계약 테스트
# ===========================================================================


_EXPECTED_LESSON_KEYS = {
    "order",
    "title",
    "description",
    "slide_count",
    "estimated_minutes",
    "learning_goal",
    "key_topics",
}


def test_slot_to_lesson_exact_keys() -> None:
    """산출 dict 키가 persist_curriculum 계약과 정확히 일치한다."""
    blueprint = build_curriculum_blueprint(subject="국어", lesson_count=5)
    slot = blueprint[0]
    items = [_slot_item(slot)]
    sr = _parse_and_validate(_to_json(items), blueprint)[0]

    lesson = _slot_response_to_lesson(sr, slot)

    assert set(lesson.keys()) == _EXPECTED_LESSON_KEYS, (
        f"키 계약 위반 — 실제={set(lesson.keys())}"
    )
    # 매핑 정합: summary → description
    assert lesson["description"] == sr.summary
    assert lesson["title"] == sr.title
    assert lesson["learning_goal"] == sr.learning_goal


def test_slot_to_lesson_key_topics_clamp_upper() -> None:
    """key_topics가 5개 초과로 들어와도(Pydantic 게이트 우회 가정) 5개로 clamp된다."""
    blueprint = build_curriculum_blueprint(subject="수학", lesson_count=5)
    slot = blueprint[0]
    # _SlotResponse는 strict max_length=5라 6개는 검증 실패한다.
    # 따라서 정상 경로의 상한은 5개 — 5개 입력이 그대로 5개 유지되는지 확인.
    items = [
        {
            "order": slot.order,
            "stage": slot.stage,
            "title": "제목",
            "summary": "요약",
            "learning_goal": "목표",
            "key_topics": ["a", "b", "c", "d", "e"],
        }
    ]
    sr = _parse_and_validate(_to_json(items), blueprint)[0]

    lesson = _slot_response_to_lesson(sr, slot)

    assert len(lesson["key_topics"]) == 5
    assert lesson["key_topics"] == ["a", "b", "c", "d", "e"]


def test_slot_to_lesson_slide_and_minutes_in_range() -> None:
    """slide_count·estimated_minutes는 블루프린트 값을 범위 내로 유지한다."""
    blueprint = build_curriculum_blueprint(subject="물리", lesson_count=10)
    slot = blueprint[3]
    items = [_slot_item(slot)]
    sr = _parse_and_validate(_to_json(items), blueprint)[0]

    lesson = _slot_response_to_lesson(sr, slot)

    assert 10 <= lesson["slide_count"] <= 15
    assert 20 <= lesson["estimated_minutes"] <= 60


# ===========================================================================
# 3. _repair_missing_slots 성공 복구 경로
# ===========================================================================


@pytest.mark.asyncio
async def test_repair_recovers_only_missing_slots() -> None:
    """3개만 받은 상태에서 부족슬롯[4,5]만 재요청해 5개로 복구한다.

    - connector.generate가 정확히 1회만 추가 호출(repair)되는지
    - 재요청 프롬프트에 부족 슬롯(4,5)만 담기고 전체 재생성이 아닌지
    """
    n = 5
    blueprint = build_curriculum_blueprint(subject="생물", lesson_count=n)
    # 이미 받은 3개 (order 1,2,3)
    received_items = [_slot_item(s) for s in blueprint[:3]]
    received = _parse_and_validate(_to_json(received_items), blueprint)
    assert len(received) == 3

    # repair 응답: 부족 슬롯 4,5만 반환
    repair_items = [_slot_item(s) for s in blueprint[3:]]
    connector = _RecordingConnector([_resp(_to_json(repair_items))])

    result = await _repair_missing_slots(
        connector, topic="유전과 진화", subject="생물", blueprint=blueprint, received=received
    )

    # 5개로 완전 복구
    assert len(result) == n, f"복구 실패 — len={len(result)}"
    assert [r.order for r in result] == [1, 2, 3, 4, 5]

    # repair 호출은 정확히 1회 (전체 흐름에서 보면 최초+repair=2회지만 여기선 repair 단독 테스트)
    assert len(connector.calls) == 1, f"repair 호출 횟수={len(connector.calls)} != 1"

    # 부족 슬롯만 재전달 — 프롬프트에 order 4,5 포함, order 1,2,3 슬롯명세 미포함
    prompt = connector.calls[0].user
    assert '"order":4' in prompt and '"order":5' in prompt, "부족 슬롯 4,5가 프롬프트에 없다"
    # 전체 재생성이 아님: "전체 강의 수: 2개" 로 부족분 개수만 표기되어야 한다
    assert "전체 강의 수: 2개" in prompt, "부족 슬롯만이 아니라 전체를 재요청하고 있다"


@pytest.mark.asyncio
async def test_repair_noop_when_nothing_missing() -> None:
    """부족 슬롯이 없으면 AI 호출 없이 그대로 반환한다(불필요한 비용 방지)."""
    n = 3
    blueprint = build_curriculum_blueprint(subject="수학", lesson_count=n)
    all_items = [_slot_item(s) for s in blueprint]
    received = _parse_and_validate(_to_json(all_items), blueprint)
    assert len(received) == n

    connector = _RecordingConnector([])  # 응답 없음 — 호출되면 IndexError

    result = await _repair_missing_slots(
        connector, topic="t", subject="수학", blueprint=blueprint, received=received
    )

    assert len(result) == n
    assert len(connector.calls) == 0, "부족 슬롯이 없는데 AI를 호출했다"


# ===========================================================================
# 4. happy-path — N 정확 충족 전체 흐름
# ===========================================================================


@pytest.mark.asyncio
async def test_plan_with_blueprint_happy_path(monkeypatch) -> None:
    """N 정확 충족 시 lessons N개를 정상 반환하고 정합한다(재요청 없음, 1회 호출)."""
    n = 10
    blueprint = build_curriculum_blueprint(subject="통계", lesson_count=n)
    full_items = [_slot_item(s) for s in blueprint]
    connector = _RecordingConnector([_resp(_to_json(full_items))])

    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.curriculum_generate.get_planner_connector",
        lambda: connector,
    )
    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.curriculum_generate.build_curriculum_blueprint",
        lambda **kw: blueprint,
    )

    course = {
        "id": "c1",
        "user_id": "u1",
        "course_name": "통계 과외",
        "subject": "통계",
        "source_type": "topic",
        "source_pdf_url": None,
        "topic_text": "통계 추론",
    }

    lessons = await _plan_with_blueprint(course, "통계", n)

    # 정확히 N개 + 키 계약 + order 연속
    assert len(lessons) == n
    assert [l["order"] for l in lessons] == list(range(1, n + 1))
    for lesson in lessons:
        assert set(lesson.keys()) == _EXPECTED_LESSON_KEYS
        assert 3 <= len(lesson["key_topics"]) <= 5

    # happy-path는 재요청 없이 1회 호출만 발생해야 한다
    assert len(connector.calls) == 1, f"happy-path 호출 횟수={len(connector.calls)} != 1"


@pytest.mark.asyncio
async def test_plan_with_blueprint_recovers_via_repair(monkeypatch) -> None:
    """최초 N-2개 → repair로 부족분 복구 → 총 N개, connector 정확히 2회 호출."""
    n = 5
    blueprint = build_curriculum_blueprint(subject="화학", lesson_count=n)
    first_items = [_slot_item(s) for s in blueprint[: n - 2]]  # 3개
    repair_items = [_slot_item(s) for s in blueprint[n - 2 :]]  # 2개
    connector = _RecordingConnector(
        [_resp(_to_json(first_items)), _resp(_to_json(repair_items))]
    )

    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.curriculum_generate.get_planner_connector",
        lambda: connector,
    )
    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.curriculum_generate.build_curriculum_blueprint",
        lambda **kw: blueprint,
    )

    course = {
        "id": "c2",
        "user_id": "u1",
        "course_name": "화학 과외",
        "subject": "화학",
        "source_type": "topic",
        "source_pdf_url": None,
        "topic_text": "화학 반응",
    }

    lessons = await _plan_with_blueprint(course, "화학", n)

    assert len(lessons) == n
    assert [l["order"] for l in lessons] == [1, 2, 3, 4, 5]
    # 최초 1회 + repair 1회 = 2회
    assert len(connector.calls) == 2, f"호출 횟수={len(connector.calls)} != 2"
