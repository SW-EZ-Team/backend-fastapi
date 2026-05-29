"""TTS V2 — FastAPI 앱 진입점.

uvicorn 실행 명령: uv run uvicorn TTS_V2.app.main:app --port 8010
브라우저 테스트 HTML은 /static/ 경로로 서빙된다.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.modules.TTS_V2.app.routers.tts_v2 import router
from app.modules.TTS_V2.app.routers.voice_profile_router import router as vp_router

# 정적 파일 디렉터리 — TTS_V2/static/
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="TTS V2 — Audiobook Pipeline",
    version="2.0.0",
    description="LangGraph 기반 오디오북 TTS 파이프라인 API",
)

# 브라우저 테스트 HTML에서 제약 없이 접근할 수 있도록 CORS 전체 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 테스트 HTML 파일 서빙 — 디렉터리가 없으면 StaticFiles 마운트를 건너뛴다
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(router, prefix="/api/tts-v2")
app.include_router(vp_router, prefix="/api/tts-v2/voice-profiles")
