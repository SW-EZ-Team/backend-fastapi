"""curriculum_blueprint — plan-first 단위 테스트.

AI 실호출 없이 블루프린트 재현성·슬롯 수·단계배분·주제 분배·order 연속성,
그리고 슬롯 검증 게이트가 N 미달을 실제로 잡는지 검증한다.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.ChapterStudio_V1.app.curriculum_blueprint import (
    CURRICULUM_MAX_LESSONS,
    CURRICULUM_MIN_LESSONS,
    ChapterSlot,
    build_curriculum_blueprint,
)
from app.modules.ChapterStudio_V1.app.curriculum_stages import STAGES


# ---------------------------------------------------------------------------
# 재현성 테스트 — 동일 입력 2회 → 동일 슬롯
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [5, 10, 15, 20])
def test_blueprint_reproducibility(n: int) -> None:
    """동일 입력은 항상 동일한 블루프린트를 반환해야 한다(재현성)."""
    kwargs = dict(subject="수학", difficulty="medium", lesson_count=n)
    first = build_curriculum_blueprint(**kwargs)
    second = build_curriculum_blueprint(**kwargs)

    assert len(first) == len(second) == n
    for a, b in zip(first, second):
        assert a == b, f"order={a.order}에서 슬롯 불일치 — {a} != {b}"


# ---------------------------------------------------------------------------
# 슬롯 수 정확성 테스트
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 5, 10, 15, 20, 30])
def test_blueprint_exact_count(n: int) -> None:
    """build_curriculum_blueprint는 lesson_count와 정확히 같은 수의 슬롯을 반환한다."""
    slots = build_curriculum_blueprint(subject="과학", lesson_count=n)
    assert len(slots) == n, f"len(slots)={len(slots)} != {n}"


# ---------------------------------------------------------------------------
# order 1..N 연속 테스트
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [5, 10, 15, 20])
def test_blueprint_order_continuous(n: int) -> None:
    """order는 1부터 N까지 연속 정수 오름차순이어야 한다."""
    slots = build_curriculum_blueprint(subject="영어", lesson_count=n)
    orders = [s.order for s in slots]
    assert orders == list(range(1, n + 1)), f"order 불연속 — {orders}"


# ---------------------------------------------------------------------------
# stage 결정적 배분 테스트
# ---------------------------------------------------------------------------


def test_stage_15_one_to_one() -> None:
    """N=15일 때 STAGES 15개가 1:1로 배정되어야 한다."""
    slots = build_curriculum_blueprint(subject="물리", lesson_count=15)
    actual_stages = [s.stage for s in slots]
    assert actual_stages == list(STAGES), f"1:1 매핑 실패 — {actual_stages}"


def test_stage_5_subset_of_stages() -> None:
    """N=5일 때 반환되는 모든 stage는 STAGES 항목 중 하나여야 한다."""
    slots = build_curriculum_blueprint(subject="화학", lesson_count=5)
    for s in slots:
        assert s.stage in STAGES, f"{s.stage!r}가 STAGES에 없다"


def test_stage_20_covers_all_when_repeated() -> None:
    """N=20(>15)일 때 모든 슬롯의 stage가 STAGES 안에 있어야 한다."""
    slots = build_curriculum_blueprint(subject="역사", lesson_count=20)
    for s in slots:
        assert s.stage in STAGES, f"{s.stage!r}가 STAGES에 없다"
    # 최소 15개 고유 stage가 등장해야 한다 (순환 패턴 확인)
    unique_stages = {s.stage for s in slots}
    assert len(unique_stages) == len(STAGES), (
        f"N=20에서 고유 stage={len(unique_stages)}개 — 15개 모두 사용되어야 한다"
    )


# ---------------------------------------------------------------------------
# topic_scope 분배 테스트
# ---------------------------------------------------------------------------


def test_topic_scope_covers_detected_topics() -> None:
    """detected_topics의 각 항목이 최소 한 슬롯의 topic_scope에 포함되어야 한다."""
    topics = ["세포 분열", "유전자 발현", "진화", "생태계"]
    slots = build_curriculum_blueprint(
        subject="생물", lesson_count=15, detected_topics=topics
    )
    for topic in topics:
        found = any(topic in s.topic_scope for s in slots)
        assert found, f"detected_topic={topic!r}가 어떤 슬롯의 topic_scope에도 없다"


def test_topic_scope_fallback_when_no_topics() -> None:
    """detected_topics가 없을 때 subject 기반 기본 범위로 채워져야 한다."""
    slots = build_curriculum_blueprint(subject="수학", lesson_count=10)
    for s in slots:
        assert "수학" in s.topic_scope, (
            f"order={s.order}: subject='수학'이 topic_scope에 없다 — {s.topic_scope!r}"
        )


# ---------------------------------------------------------------------------
# 슬롯 구조 무결성 테스트
# ---------------------------------------------------------------------------


def test_slot_fields_populated() -> None:
    """모든 슬롯의 필수 필드가 채워져 있어야 한다."""
    slots = build_curriculum_blueprint(subject="국어", lesson_count=10)
    for s in slots:
        assert s.order >= 1
        assert s.stage
        assert s.topic_scope
        assert s.role in {"도입", "탐구", "심화", "적용", "마무리"}
        assert 10 <= s.slide_count <= 15
        assert 20 <= s.estimated_minutes <= 60
        assert len(s.key_topics) == 3  # 힌트는 항상 3개


def test_blueprint_invalid_count_raises() -> None:
    """허용 범위를 벗어난 lesson_count는 ValueError를 발생시켜야 한다."""
    with pytest.raises(ValueError):
        build_curriculum_blueprint(subject="테스트", lesson_count=0)
    with pytest.raises(ValueError):
        build_curriculum_blueprint(subject="테스트", lesson_count=31)


# ---------------------------------------------------------------------------
# 슬롯 검증 게이트 테스트 — N 미달을 실제로 잡는지 확인
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_with_blueprint_raises_on_shortage(monkeypatch) -> None:
    """AI가 N-1개만 반환하면 _plan_with_blueprint가 ValueError를 발생시켜야 한다.

    generate_and_store_curriculum 공개 경로까지 가지 않고
    내부 _plan_with_blueprint를 직접 테스트해 실패 경로를 검증한다.
    """
    from app.modules.ChapterStudio_V1.app.curriculum_generate import _plan_with_blueprint
    from app.modules.ChapterStudio_V1.app.curriculum_stages import STAGES
    from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIResponse

    n = 5
    # N-1개(4개)만 담긴 AI 응답 — stage는 블루프린트와 일치시켜 파싱이 성공하도록 함
    blueprint_for_test = build_curriculum_blueprint(subject="테스트", lesson_count=n)
    # 첫 4개 슬롯만 반환하는 mock 응답 구성
    partial_items = []
    for slot in blueprint_for_test[:n - 1]:
        partial_items.append({
            "order": slot.order,
            "stage": slot.stage,
            "title": f"테스트 {slot.order}강",
            "summary": "테스트 요약",
            "learning_goal": "학습 목표",
            "key_topics": ["키1", "키2", "키3"],
        })

    fake_response = ChapterAIResponse(
        text=json.dumps(partial_items, ensure_ascii=False),
        model="test-model",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
    )

    # 커넥터 mock: 첫 번째 호출(전체 요청) → N-1개, 두 번째(repair) → 0개 반환
    mock_connector = AsyncMock()
    mock_connector.generate = AsyncMock(return_value=fake_response)

    # 빈 repair 응답 준비 (두 번째 호출 시)
    empty_response = ChapterAIResponse(
        text="[]",
        model="test-model",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
    )
    mock_connector.generate.side_effect = [fake_response, empty_response]

    # AIConnector isinstance 체크를 통과시키기 위해 spec 설정
    from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector
    mock_connector.__class__ = type(
        "MockAIConnector",
        (AIConnector,),
        {"generate": mock_connector.generate},
    )

    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.curriculum_generate.get_planner_connector",
        lambda: mock_connector,
    )
    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.curriculum_generate.build_curriculum_blueprint",
        lambda **kw: blueprint_for_test,
    )

    course = {
        "id": "test-course",
        "user_id": "user1",
        "course_name": "테스트 과정",
        "subject": "테스트",
        "source_type": "topic",
        "source_pdf_url": None,
        "topic_text": "테스트 주제",
    }

    with pytest.raises(ValueError, match="슬롯.*미충족"):
        await _plan_with_blueprint(course, "테스트", n)


@pytest.mark.asyncio
async def test_generate_and_store_marks_failed_on_shortage(monkeypatch) -> None:
    """N 미달 시 mark_course_curriculum_failed가 호출되어야 한다."""
    from app.modules.ChapterStudio_V1.app.curriculum_generate import (
        generate_and_store_curriculum,
    )
    from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIResponse

    n = 5
    blueprint_for_test = build_curriculum_blueprint(subject="테스트", lesson_count=n)

    # N-1개만 반환하는 응답 2회 (전체 + repair 모두 실패)
    partial_items = [
        {
            "order": slot.order,
            "stage": slot.stage,
            "title": f"테스트 {slot.order}강",
            "summary": "테스트 요약",
            "learning_goal": "학습 목표",
            "key_topics": ["키1", "키2", "키3"],
        }
        for slot in blueprint_for_test[:n - 1]
    ]
    short_response = ChapterAIResponse(
        text=json.dumps(partial_items, ensure_ascii=False),
        model="test",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
    )

    from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector

    class FakeConnector(AIConnector):
        async def generate(self, req):
            return short_response

    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.curriculum_generate.get_planner_connector",
        FakeConnector,
    )
    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.curriculum_generate.build_curriculum_blueprint",
        lambda **kw: blueprint_for_test,
    )

    course_fixture = {
        "id": "test-course-2",
        "user_id": "user1",
        "course_name": "테스트",
        "subject": "테스트",
        "source_type": "topic",
        "source_pdf_url": None,
        "topic_text": "주제",
    }

    # _load_course_after_spring_commit을 mock해 DB 접근 없이 테스트
    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.curriculum_generate._load_course_after_spring_commit",
        AsyncMock(return_value=course_fixture),
    )

    # mark_course_curriculum_failed 호출 여부 추적
    failed_reason: list[str] = []

    async def fake_mark_failed(course_id: str, reason: str) -> None:
        failed_reason.append(reason)

    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.curriculum_generate.mark_course_curriculum_failed",
        fake_mark_failed,
    )

    await generate_and_store_curriculum("test-course-2", "테스트", n, "topic")

    # 실패 경로가 발동되어야 한다
    assert len(failed_reason) >= 1, "mark_course_curriculum_failed가 호출되지 않았다"
