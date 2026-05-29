"""Agent Orchestrator 통합 테스트 — 스프링이 보내는 실제 JSON 페이로드로 검증한다.

mock, MagicMock, @patch, monkeypatch 절대 금지.
POST /api/agent/jobs 와 GET /api/agent/jobs/{job_id} 를 검증한다.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


# ─── 헬스체크 ──────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_agent_orchestrator_health(client: AsyncClient) -> None:
    """오케스트레이터 헬스체크 엔드포인트가 200을 반환하는지 확인한다."""
    response = await client.get("/api/agent/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "agent-orchestrator"


# ─── 정상 요청: chapter_studio_v1 job 생성 ────────────────────────────────────

@pytest.mark.anyio
async def test_create_chapter_studio_job(client: AsyncClient) -> None:
    """스프링이 chapter_studio_v1 job을 요청할 때 202와 job_id를 반환하는지 확인한다."""
    # 스프링이 실제로 전송하는 페이로드 구조
    payload: dict = {
        "request_id": "spring-req-20260521-001",
        "correlation_id": "corr-chapter-studio-20260521",
        "idempotency_key": "idem-python-list-comp-lesson-001",
        "module": "chapter_studio_v1",
        "action": "curriculum_preview",
        "payload": {
            "topic": "Python 리스트 컴프리헨션",
            "source_mode": "topic",
            "duration_days": 30,
            "depth": "normal",
            "teacher": "owl",
            "tone": 50,
            "pace": 50,
            "tutor_depth": 60,
            "socratic": 70,
            "audience_level": "프로그래밍 입문자",
            "learning_goal": "리스트 컴프리헨션의 문법과 활용법을 완전히 이해한다",
            "weak_points": "for 루프와 조건식 조합이 헷갈림",
            "chapter_title": "리스트 컴프리헨션 마스터하기",
            "chapter_brief": "반복문을 한 줄로 압축하는 파이썬의 핵심 문법",
        },
        "run_inline": False,
    }

    response = await client.post("/api/agent/jobs", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["job_id"].startswith("job_")
    assert data["module"] == "chapter_studio_v1"
    assert data["action"] == "curriculum_preview"
    assert data["status"] in {"queued", "running", "done"}
    assert data["request_id"] == "spring-req-20260521-001"


@pytest.mark.anyio
async def test_create_tts_v2_job(client: AsyncClient) -> None:
    """스프링이 tts_v2 job을 요청할 때 202와 올바른 job 레코드를 반환한다."""
    payload: dict = {
        "request_id": "spring-tts-req-20260521-002",
        "module": "tts_v2",
        "action": "synthesize",
        "payload": {
            "text": "안녕하세요. 오늘 강의 내용을 음성으로 합성합니다.",
            "language": "ko",
            "speed": 1.0,
        },
        "run_inline": False,
    }

    response = await client.post("/api/agent/jobs", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert data["module"] == "tts_v2"
    assert data["status"] in {"queued", "running", "done"}


@pytest.mark.anyio
async def test_create_exam_forge_job(client: AsyncClient) -> None:
    """스프링이 exam_forge_v1 job을 요청할 때 202를 반환한다."""
    payload: dict = {
        "module": "exam_forge_v1",
        "action": "generate",
        "payload": {
            "source_text": "자료구조의 기본 개념",
            "subject": "자료구조",
        },
        "run_inline": False,
    }

    response = await client.post("/api/agent/jobs", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert data["module"] == "exam_forge_v1"


# ─── job 조회 ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_job_by_id(client: AsyncClient) -> None:
    """job 생성 후 GET /api/agent/jobs/{job_id} 로 상태를 조회할 수 있다."""
    payload: dict = {
        "module": "chapter_studio_v1",
        "action": "generate_slides",
        "payload": {"topic": "운영체제 프로세스 관리"},
        "run_inline": False,
    }

    create_resp = await client.post("/api/agent/jobs", json=payload)
    assert create_resp.status_code == 202
    job_id: str = create_resp.json()["job_id"]

    get_resp = await client.get(f"/api/agent/jobs/{job_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["job_id"] == job_id
    assert data["status"] in {"queued", "running", "done", "error"}


@pytest.mark.anyio
async def test_get_nonexistent_job_returns_404(client: AsyncClient) -> None:
    """존재하지 않는 job_id 조회 시 404를 반환한다."""
    response = await client.get("/api/agent/jobs/job_nonexistent_00000000")
    assert response.status_code == 404


# ─── 유효성 검사 오류 ──────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_missing_module_field_returns_422(client: AsyncClient) -> None:
    """module 필드가 없으면 422 검증 오류를 반환한다."""
    payload: dict = {
        "action": "generate",
        "payload": {},
    }
    response = await client.post("/api/agent/jobs", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_invalid_module_value_returns_422(client: AsyncClient) -> None:
    """허용되지 않은 module 값을 전송하면 422를 반환한다."""
    payload: dict = {
        "module": "nonexistent_module_v99",
        "action": "generate",
        "payload": {},
    }
    response = await client.post("/api/agent/jobs", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_missing_action_field_returns_422(client: AsyncClient) -> None:
    """action 필드가 없으면 422 검증 오류를 반환한다."""
    payload: dict = {
        "module": "chapter_studio_v1",
        "payload": {},
    }
    response = await client.post("/api/agent/jobs", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_whitespace_only_action_treated_as_null(client: AsyncClient) -> None:
    """공백만으로 이루어진 action은 None으로 처리되어 422를 반환한다."""
    payload: dict = {
        "module": "chapter_studio_v1",
        "action": "   ",
        "payload": {},
    }
    response = await client.post("/api/agent/jobs", json=payload)
    # 공백 action은 validator가 None으로 변환하여 min_length 위반 → 422
    assert response.status_code == 422
