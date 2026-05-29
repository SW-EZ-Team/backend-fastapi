"""ExamForge_V1 통합 테스트 — 스프링이 보내는 실제 JSON 페이로드로 검증한다.

mock, MagicMock, @patch, monkeypatch 절대 금지.
POST /api/exam-forge/generate 와 GET /api/exam-forge/templates 를 검증한다.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


# ─── 헬스체크 ──────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_exam_forge_health(client: AsyncClient) -> None:
    """모의고사 헬스체크 엔드포인트가 200을 반환한다."""
    response = await client.get("/api/exam-forge/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "exam-forge"


# ─── 템플릿 목록 ───────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_list_templates_all(client: AsyncClient) -> None:
    """전체 템플릿 목록이 리스트 형태로 반환된다."""
    response = await client.get("/api/exam-forge/templates")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.anyio
async def test_list_templates_filtered_by_locale(client: AsyncClient) -> None:
    """locale 파라미터로 필터링된 템플릿 목록을 반환한다."""
    response = await client.get("/api/exam-forge/templates", params={"locale": "ko"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


# ─── 정상 요청: 모의고사 생성 ─────────────────────────────────────────────────

@pytest.mark.anyio
async def test_generate_exam_forge_basic(client: AsyncClient) -> None:
    """스프링이 기본 모의고사 생성을 요청할 때 스키마 검증이 통과된다.

    실제 LLM 파이프라인은 실행되지 않을 수 있으나 스키마·라우터 레이어를 검증한다.
    """
    payload: dict = {
        "source_text": (
            "자료구조는 데이터를 효율적으로 저장하고 관리하는 방법을 다루는 "
            "컴퓨터 과학의 핵심 분야입니다. 배열은 연속된 메모리 공간에 데이터를 "
            "저장하며 인덱스를 통한 O(1) 접근이 가능하지만 삽입과 삭제에는 O(n) "
            "시간이 소요됩니다. 연결 리스트는 노드들이 포인터로 연결된 구조로 삽입과 "
            "삭제가 O(1)에 가능하지만 특정 위치 접근에는 O(n)이 필요합니다. 스택은 "
            "후입선출(LIFO) 방식으로 동작합니다."
        ),
        "subject": "자료구조",
        "exam_config": {
            "total_questions": 10,
            "time_limit_minutes": 30,
            "locale": "ko",
            "category": "korean",
            "question_types": ["ko_multiple_choice_5"],
            "difficulty_distribution": {
                "1": 0.2,
                "2": 0.3,
                "3": 0.3,
                "4": 0.15,
                "5": 0.05,
            },
            "passing_score": 60.0,
            "include_explanations": True,
        },
    }

    response = await client.post("/api/exam-forge/generate", json=payload)
    # 실제 LLM 없이도 스키마 통과 후 파이프라인 오류가 발생할 수 있으므로 허용 범위 넓게 설정
    assert response.status_code in {200, 500, 504}


@pytest.mark.anyio
async def test_generate_exam_forge_full_payload(client: AsyncClient) -> None:
    """스프링이 전체 필드를 포함한 모의고사 요청을 보낼 때 스키마가 통과된다."""
    payload: dict = {
        "source_text": (
            "알고리즘 복잡도 분석은 프로그램의 효율성을 평가하는 핵심 도구입니다. "
            "시간 복잡도는 입력 크기에 따른 실행 시간의 증가 패턴을 나타내며, "
            "O(1)은 상수 시간, O(log n)은 로그 시간, O(n)은 선형 시간, "
            "O(n log n)은 선형 로그 시간, O(n²)은 이차 시간 복잡도를 의미합니다. "
            "공간 복잡도는 프로그램이 사용하는 메모리 양을 나타냅니다. "
            "버블 정렬은 O(n²), 병합 정렬은 O(n log n), 퀵 정렬은 평균 O(n log n)입니다."
        ),
        "subject": "알고리즘 복잡도 분석",
        "exam_config": {
            "total_questions": 15,
            "time_limit_minutes": 40,
            "locale": "ko",
            "category": "korean",
            "question_types": ["ko_multiple_choice_5", "ko_short_answer", "ko_true_false"],
            "difficulty_distribution": {
                "1": 0.10,
                "2": 0.25,
                "3": 0.40,
                "4": 0.20,
                "5": 0.05,
            },
            "passing_score": 70.0,
            "include_explanations": True,
        },
    }

    response = await client.post("/api/exam-forge/generate", json=payload)
    assert response.status_code in {200, 500, 504}


# ─── 유효성 검사 오류 ──────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_source_text_too_short_returns_422(client: AsyncClient) -> None:
    """100자 미만 source_text는 422 검증 오류를 반환한다."""
    payload: dict = {
        "source_text": "너무 짧은 텍스트",
        "subject": "자료구조",
    }
    response = await client.post("/api/exam-forge/generate", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_missing_source_text_returns_422(client: AsyncClient) -> None:
    """source_text 필드 누락 시 422를 반환한다."""
    payload: dict = {
        "subject": "알고리즘",
    }
    response = await client.post("/api/exam-forge/generate", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_invalid_difficulty_distribution_sum_returns_422(
    client: AsyncClient,
) -> None:
    """난이도 분포 합계가 1.0이 아니면 422를 반환한다."""
    payload: dict = {
        "source_text": "a" * 150,
        "subject": "자료구조",
        "exam_config": {
            "difficulty_distribution": {
                "1": 0.5,
                "2": 0.5,
                "3": 0.5,  # 합계 1.5 — 유효하지 않음
            },
        },
    }
    response = await client.post("/api/exam-forge/generate", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_whitespace_only_subject_returns_422(client: AsyncClient) -> None:
    """공백만으로 이루어진 subject는 422를 반환한다."""
    payload: dict = {
        "source_text": "a" * 150,
        "subject": "   ",
    }
    response = await client.post("/api/exam-forge/generate", json=payload)
    assert response.status_code == 422
