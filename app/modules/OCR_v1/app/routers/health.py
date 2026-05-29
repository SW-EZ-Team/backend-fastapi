"""OCR v1 헬스체크 라우터."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["운영"], summary="OCR v1 헬스체크")
async def health() -> dict[str, str]:
    """OCR v1 라우터가 backend-fastapi에 정상 연결되었는지 확인한다."""
    return {"status": "ok", "service": "ocr-v1-pipeline"}
