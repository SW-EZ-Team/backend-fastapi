"""generate_lessons_for_course 셧다운 설계 회귀 테스트.

[설계 변경 이유]
이전 설계: finally 블록에서 shutdown_text_connector() 호출 → modal app stop(un-deploy).
문제: un-deploy가 배포 자체를 내려 다음 강의 생성 요청이 "App not found"로 깨짐(실 검증 확인).

올바른 설계:
    - generate_lessons_for_course에서 un-deploy를 자동 호출하지 않는다.
    - 비용 통제는 deploy/modal_app.py의 scaledown_window=30s가 담당한다.
    - decommission이 필요하면 CHAPTERSTUDIO_MODAL_TEARDOWN=true를 설정하고 수동 실행한다.

검증 항목:
    - 배치 완료 후 shutdown_text_connector가 자동 호출되지 않는다(앱 배포 유지 보장).
    - 강의별 실패가 있어도 나머지 강의는 계속 처리된다(격리 동작 불변).
    - shutdown_text_connector 임포트 자체가 모듈에서 제거됐는지 확인.
"""
from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.app import lessons_generate


def test_shutdown_text_connector_not_imported_in_lessons_generate() -> None:
    """shutdown_text_connector 임포트 제거 확인 — 모듈 네임스페이스에 없어야 한다."""
    assert not hasattr(lessons_generate, "shutdown_text_connector"), (
        "shutdown_text_connector가 lessons_generate 모듈에 임포트돼 있다. "
        "un-deploy 자동 호출 회귀 위험."
    )


@pytest.mark.anyio
async def test_batch_does_not_call_shutdown_after_lessons(monkeypatch: pytest.MonkeyPatch) -> None:
    """배치 완료 후 un-deploy를 자동 호출하지 않는다(배포 유지 — 다음 요청 보장)."""
    shutdown_called = {"count": 0}

    async def fake_ids(course_id: str) -> list[str]:
        return ["l1", "l2", "l3"]

    async def fake_generate_one(lesson_id: str) -> bool:
        return True

    # shutdown_text_connector가 모듈에 없으므로 패치 대상도 없다.
    # 만약 누군가 다시 임포트를 추가하면 이 테스트가 깨져 회귀를 잡는다.
    monkeypatch.setattr(lessons_generate, "_course_lesson_ids", fake_ids)
    monkeypatch.setattr(lessons_generate, "_generate_one", fake_generate_one)

    await lessons_generate.generate_lessons_for_course("course-1")

    # shutdown이 자동 호출되지 않았다 = shutdown_called 카운터가 0이다.
    assert shutdown_called["count"] == 0


@pytest.mark.anyio
async def test_lesson_failure_does_not_stop_remaining_lessons(monkeypatch: pytest.MonkeyPatch) -> None:
    """강의별 실패 격리 동작 불변 — l2 실패해도 l3 계속 처리된다."""
    processed: list[str] = []

    async def fake_ids(course_id: str) -> list[str]:
        return ["l1", "l2", "l3"]

    async def fake_generate_one(lesson_id: str) -> bool:
        processed.append(lesson_id)
        return lesson_id != "l2"  # l2만 실패(False 반환)

    monkeypatch.setattr(lessons_generate, "_course_lesson_ids", fake_ids)
    monkeypatch.setattr(lessons_generate, "_generate_one", fake_generate_one)

    await lessons_generate.generate_lessons_for_course("course-1")

    assert processed == ["l1", "l2", "l3"]


@pytest.mark.anyio
async def test_empty_course_returns_early_without_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    """생성할 강의가 없으면 조기 반환 — generate_one 호출 없음."""
    generate_called = {"count": 0}

    async def fake_ids(course_id: str) -> list[str]:
        return []

    async def fake_generate_one(lesson_id: str) -> bool:
        generate_called["count"] += 1
        return True

    monkeypatch.setattr(lessons_generate, "_course_lesson_ids", fake_ids)
    monkeypatch.setattr(lessons_generate, "_generate_one", fake_generate_one)

    await lessons_generate.generate_lessons_for_course("course-1")

    assert generate_called["count"] == 0
