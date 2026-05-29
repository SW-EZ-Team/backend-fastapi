"""ASR V1 — FastAPI 앱 진입점.

uvicorn 실행 명령: uv run uvicorn app.modules.ASR_V1.app.main:app --port 8011
lifespan에서 Silero VAD를 사전 로드해 첫 WS 연결 지연을 방지한다.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.modules.ASR_V1.app.routers.asr_v1 import router
from app.modules.ASR_V1.pipeline.vad import SileroVAD

# 정적 파일 디렉터리 — ASR_V1/static/
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """앱 시작 시 Silero VAD 사전 로드 — 첫 WS 연결 지연 방지."""
    # 싱글톤 모델 로드 트리거 (torch.hub 캐시 사용)
    SileroVAD._ensure_model()
    yield
    # 종료 시 별도 정리 불필요 (torch 모델은 GC에 위임)


app = FastAPI(
    title="ASR V1 — 실시간 대화형 ASR 파이프라인",
    version="1.0.0",
    description="Silero VAD + 배치 ASR 기반 pseudo-streaming 전사 API",
    lifespan=lifespan,
)

# 브라우저 테스트 HTML에서 제약 없이 접근할 수 있도록 CORS 전체 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 테스트 HTML 파일 서빙 — 디렉터리가 없으면 마운트 건너뜀
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(router)
