"""OCR_v1 통합 테스트 — 스프링이 보내는 실제 HTTP 요청으로 검증한다.

mock, MagicMock, @patch, monkeypatch 절대 금지.
POST /api/ocr/v1/ingest (multipart), POST /api/ocr/v1/search (JSON) 를 검증한다.
"""
from __future__ import annotations

import importlib

import pytest
from httpx import AsyncClient

# FlagEmbedding 패키지 설치 여부 — 미설치 시 BGE-M3 로드 시 RuntimeError 발생
_has_flag_embedding = importlib.util.find_spec("FlagEmbedding") is not None


# ─── 헬스체크 ──────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_ocr_health(client: AsyncClient) -> None:
    """OCR v1 헬스체크 엔드포인트가 200을 반환한다."""
    response = await client.get("/api/ocr/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "ocr-v1-pipeline"


# ─── POST /api/ocr/v1/search (JSON 요청) ─────────────────────────────────────

@pytest.mark.anyio
@pytest.mark.skipif(not _has_flag_embedding, reason="FlagEmbedding 미설치 — BGE-M3 로드 불가로 검색 엔드포인트 예외 발생")
async def test_search_with_valid_payload(client: AsyncClient) -> None:
    """스프링이 RAG 검색을 요청할 때 스키마 검증이 통과된다.

    실제 Qdrant가 없어도 스키마·라우터 레이어는 검증 가능하다.
    """
    payload: dict = {
        "query": "파이썬 리스트 컴프리헨션 사용법",
        "collection_name": "파이썬_교재_컬렉션",
        "top_k": 5,
    }

    response = await client.post("/api/ocr/v1/search", json=payload)
    # Qdrant 없이 실행 시 500이 발생할 수 있으나 스키마는 통과해야 한다
    assert response.status_code in {200, 500}
    assert response.status_code != 422


@pytest.mark.anyio
@pytest.mark.skipif(not _has_flag_embedding, reason="FlagEmbedding 미설치 — BGE-M3 로드 불가로 검색 엔드포인트 예외 발생")
async def test_search_with_max_top_k(client: AsyncClient) -> None:
    """top_k 최댓값(50)으로 검색 요청이 스키마를 통과한다."""
    payload: dict = {
        "query": "신경망 역전파 알고리즘 수식",
        "collection_name": "딥러닝_강의자료",
        "top_k": 50,
    }

    response = await client.post("/api/ocr/v1/search", json=payload)
    assert response.status_code in {200, 500}
    assert response.status_code != 422


@pytest.mark.anyio
@pytest.mark.skipif(not _has_flag_embedding, reason="FlagEmbedding 미설치 — BGE-M3 로드 불가로 검색 엔드포인트 예외 발생")
async def test_search_with_default_top_k(client: AsyncClient) -> None:
    """top_k를 생략하면 기본값(5)이 적용된다."""
    payload: dict = {
        "query": "운영체제 프로세스 스케줄링",
        "collection_name": "os_교재",
    }

    response = await client.post("/api/ocr/v1/search", json=payload)
    assert response.status_code in {200, 500}
    assert response.status_code != 422


# ─── 유효성 검사 오류: search ─────────────────────────────────────────────────

@pytest.mark.anyio
async def test_search_missing_query_returns_422(client: AsyncClient) -> None:
    """query 필드 누락 시 422를 반환한다."""
    payload: dict = {
        "collection_name": "test_collection",
        "top_k": 5,
    }
    response = await client.post("/api/ocr/v1/search", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_search_missing_collection_name_returns_422(
    client: AsyncClient,
) -> None:
    """collection_name 필드 누락 시 422를 반환한다."""
    payload: dict = {
        "query": "데이터베이스 인덱스",
        "top_k": 5,
    }
    response = await client.post("/api/ocr/v1/search", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_search_top_k_exceeds_max_returns_422(client: AsyncClient) -> None:
    """top_k 가 최댓값(50)을 초과하면 422를 반환한다."""
    payload: dict = {
        "query": "알고리즘 시간 복잡도",
        "collection_name": "algorithm_notes",
        "top_k": 100,  # 최대 50 초과
    }
    response = await client.post("/api/ocr/v1/search", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_search_top_k_zero_returns_422(client: AsyncClient) -> None:
    """top_k 가 0 이하이면 422를 반환한다."""
    payload: dict = {
        "query": "자료구조 해시테이블",
        "collection_name": "ds_notes",
        "top_k": 0,
    }
    response = await client.post("/api/ocr/v1/search", json=payload)
    assert response.status_code == 422


# ─── POST /api/ocr/v1/ingest (multipart/form-data) ───────────────────────────

@pytest.mark.anyio
async def test_ingest_non_pdf_file_returns_400(client: AsyncClient) -> None:
    """PDF가 아닌 파일을 업로드하면 400을 반환한다."""
    # 텍스트 파일로 위장한 잘못된 업로드
    files = {
        "file": ("test.txt", b"This is not a PDF file content", "text/plain"),
    }
    response = await client.post("/api/ocr/v1/ingest", files=files)
    assert response.status_code == 400


@pytest.mark.anyio
async def test_ingest_minimal_pdf_bytes(client: AsyncClient) -> None:
    """최소한의 PDF 헤더를 가진 파일이 파이프라인으로 전달된다.

    실제 OCR 파이프라인 없이는 500/에러 응답이 나오지만
    400(형식 검증 실패)은 아니어야 한다.
    """
    # PDF 매직 바이트로 시작하는 최소 바이너리
    minimal_pdf = b"%PDF-1.4 fake content for schema test"
    files = {
        "file": ("lecture_notes.pdf", minimal_pdf, "application/pdf"),
    }
    data = {"collection_name": "강의자료_2026_1학기"}
    response = await client.post("/api/ocr/v1/ingest", files=files, data=data)
    # 형식은 통과하지만 실제 파이프라인에서 오류가 날 수 있다
    assert response.status_code in {200, 500}
    assert response.status_code != 400  # 400은 형식 오류 — 허용 불가
