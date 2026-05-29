"""OCR v1 backend-fastapi 통합 스모크 테스트."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.modules.OCR_v1 import OCRv1Pipeline, health_router, ingest_router, search_router
from main import app


def test_public_exports_are_importable() -> None:
    """backend-fastapi에서 공개 진입점과 라우터를 import할 수 있어야 한다."""
    assert OCRv1Pipeline().supports("pdf_ingest") is True
    assert health_router is not None
    assert ingest_router is not None
    assert search_router is not None


def test_ocr_routes_are_registered() -> None:
    """통합 앱에 OCR prefix가 한 번만 붙은 라우트가 등록되어야 한다."""
    paths = {route.path for route in app.routes}
    assert "/api/ocr/v1/health" in paths
    assert "/api/ocr/v1/ingest" in paths
    assert "/api/ocr/v1/search" in paths
    assert "/api/ocr/v1/api/ocr/v1/ingest" not in paths


def test_ocr_health_endpoint() -> None:
    """OCR v1 헬스체크가 정상 응답해야 한다."""
    client = TestClient(app)
    res = client.get("/api/ocr/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "ocr-v1-pipeline"}


def test_ingest_rejects_non_pdf_upload() -> None:
    """PDF가 아닌 파일은 실제 OCR 실행 전에 400으로 거절해야 한다."""
    client = TestClient(app)
    res = client.post(
        "/api/ocr/v1/ingest",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 400
    assert "PDF" in res.json()["detail"]


def test_search_request_schema_is_active() -> None:
    """검색 요청 schema가 라우터에 연결되어 누락 필드를 422로 검증해야 한다."""
    client = TestClient(app)
    res = client.post("/api/ocr/v1/search", json={})
    assert res.status_code == 422
