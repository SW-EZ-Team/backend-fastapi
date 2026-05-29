"""ExamForge_V1 샌드박스 서버."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.modules.ExamForge_V1.app.routers.exam_forge import router
from app.modules.ExamForge_V1.common.config import log_level

# 루트 로거 레벨을 환경 변수에서 읽어 적용한다
logging.basicConfig(level=getattr(logging, log_level().upper(), logging.INFO))

_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

app = FastAPI(title="ExamForge_V1 Sandbox", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    """테스트 페이지를 반환한다."""
    return FileResponse(str(_STATIC_DIR / "mock_exam_test.html"))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """헬스체크 엔드포인트."""
    return {"status": "ok"}
