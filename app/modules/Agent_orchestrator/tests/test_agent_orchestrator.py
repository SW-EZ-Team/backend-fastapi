"""Agent orchestrator 통합 테스트."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.modules.Agent_orchestrator import runner
from main import app


def test_agent_health_endpoint() -> None:
    """오케스트레이터 헬스체크가 응답해야 한다."""
    client = TestClient(app)
    res = client.get("/api/agent/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "agent-orchestrator"
    assert body["job_store"]
    assert body["executor"]


def test_chapter_studio_curriculum_preview_inline_job() -> None:
    """짧은 ChapterStudio preview job을 실제 어댑터로 즉시 실행한다."""
    client = TestClient(app)
    res = client.post(
        "/api/agent/jobs",
        json={
            "module": "chapter_studio_v1",
            "action": "curriculum_preview",
            "run_inline": True,
            "payload": {
                "title": "Rust 중급 커리큘럼",
                "topic": "Rust 소유권과 비동기",
                "subject": "프로그래밍",
                "lesson_count": 10,
                "engine": "mock",
            },
        },
    )
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "done"
    assert body["result"]["status"] == "CURRICULUM_READY"
    assert len(body["result"]["lessons"]) == 10

    result = client.get(f"/api/agent/jobs/{body['job_id']}/result")
    assert result.status_code == 200
    assert result.json()["title"] == "Rust 중급 커리큘럼"


def test_unknown_action_records_error() -> None:
    """지원하지 않는 action은 job error 상태로 기록되어야 한다."""
    client = TestClient(app)
    res = client.post(
        "/api/agent/jobs",
        json={
            "module": "chapter_studio_v1",
            "action": "not_supported",
            "run_inline": True,
            "payload": {"topic": "Rust"},
        },
    )
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "error"
    assert body["error_code"] == "ValueError"


def test_idempotency_key_returns_existing_job() -> None:
    """같은 idempotency_key 요청은 중복 생성하지 않고 기존 job을 반환한다."""
    client = TestClient(app)
    payload = {
        "idempotency_key": "idem-rust-preview-001",
        "module": "chapter_studio_v1",
        "action": "curriculum_preview",
        "run_inline": True,
        "payload": {
            "title": "Rust 중복 방지 커리큘럼",
            "topic": "Rust 소유권",
            "subject": "프로그래밍",
            "lesson_count": 10,
            "engine": "mock",
        },
    }

    first = client.post("/api/agent/jobs", json=payload)
    second = client.post("/api/agent/jobs", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]


def test_callback_status_is_recorded(monkeypatch) -> None:
    """callback_url이 있으면 완료 후 callback 상태를 job record에 기록한다."""

    async def fake_post_agent_callback(record):
        assert record.callback_url == "https://spring.example.test/internal/ai/callback"
        return True, 1, None

    monkeypatch.setattr(runner, "post_agent_callback", fake_post_agent_callback)
    client = TestClient(app)
    res = client.post(
        "/api/agent/jobs",
        json={
            "request_id": "spring-request-1",
            "correlation_id": "corr-1",
            "module": "chapter_studio_v1",
            "action": "curriculum_preview",
            "callback_url": "https://spring.example.test/internal/ai/callback",
            "run_inline": True,
            "payload": {
                "title": "Callback 커리큘럼",
                "topic": "Rust Result",
                "subject": "프로그래밍",
                "lesson_count": 10,
                "engine": "mock",
            },
        },
    )

    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "done"
    assert body["callback_status"] == "sent"
    assert body["callback_attempts"] == 1
    assert body["request_id"] == "spring-request-1"
    assert body["correlation_id"] == "corr-1"
