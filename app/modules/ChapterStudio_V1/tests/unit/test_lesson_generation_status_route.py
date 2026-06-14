"""강의 생성 진행 상태 조회(GET /api/lessons/{id}/generation-status) 단위 테스트.

프론트 대기 화면이 노드 단위 진행률을 표시할 수 있도록
DB 행 → camelCase 응답 매핑과 행 없음(unknown) 폴백을 검증한다.
"""
from __future__ import annotations

from collections.abc import Mapping

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.ChapterStudio_V1.app.routers import lessons as lessons_router
from app.modules.ChapterStudio_V1.db.persistence_status import fetch_chapter_generation_status


class FakeFetchConnection:
    """fetchrow 1회 호출을 기록하고 준비된 행을 돌려주는 가짜 커넥션."""

    def __init__(self, row: Mapping[str, object] | None) -> None:
        self.row = row
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None:
        self.calls.append((query, args))
        return self.row


class FakeConnectionManager:
    """async with get_connection() 형태를 흉내 내는 컨텍스트 매니저."""

    def __init__(self, conn: object) -> None:
        self.conn = conn

    async def __aenter__(self) -> object:
        return self.conn

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


_ROW = {
    "status": "running",
    "current_node": "synthesize_audio",
    "completed_nodes": 4,
    "total_nodes": 5,
    "progress_percent": 85,
    "error_message": None,
}


@pytest.mark.anyio
async def test_fetch_chapter_generation_status_queries_lesson_id() -> None:
    conn = FakeFetchConnection(_ROW)

    result = await fetch_chapter_generation_status(conn, "lesson-1")

    query, args = conn.calls[0]
    assert "FROM chapter_studio.lesson_generation_status" in query
    assert "WHERE lesson_id = $1" in query
    assert args == ("lesson-1",)
    assert result == {
        "status": "running",
        "current_node": "synthesize_audio",
        "completed_nodes": 4,
        "total_nodes": 5,
        "progress_percent": 85,
        "error_message": None,
    }


@pytest.mark.anyio
async def test_fetch_chapter_generation_status_returns_none_without_row() -> None:
    conn = FakeFetchConnection(None)

    assert await fetch_chapter_generation_status(conn, "lesson-x") is None


def _client(monkeypatch: pytest.MonkeyPatch, row: Mapping[str, object] | None) -> TestClient:
    conn = FakeFetchConnection(row)
    monkeypatch.setattr(lessons_router, "get_connection", lambda: FakeConnectionManager(conn))
    app = FastAPI()
    app.include_router(lessons_router.router)
    return TestClient(app)


def test_generation_status_route_maps_row_to_camel_case(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, _ROW)

    response = client.get("/api/lessons/lesson-1/generation-status")

    assert response.status_code == 200
    assert response.json() == {
        "lessonId": "lesson-1",
        "status": "running",
        "currentNode": "synthesize_audio",
        "completedNodes": 4,
        "totalNodes": 5,
        "progressPercent": 85,
        "errorMessage": None,
    }


def test_generation_status_route_returns_unknown_without_row(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, None)

    response = client.get("/api/lessons/lesson-x/generation-status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unknown"
    assert body["progressPercent"] == 0
    assert body["currentNode"] is None
