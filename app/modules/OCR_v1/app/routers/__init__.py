"""라우터 패키지 — FastAPI APIRouter 인스턴스를 포함한다."""
from __future__ import annotations

from .health import router as health_router
from .ingest import router as ingest_router
from .search import router as search_router

__all__ = ["health_router", "ingest_router", "search_router"]
