"""backend-fastapi 진입점.

lifespan으로 DB 풀을 관리하고, CORS와 API 키 인증 미들웨어를 적용한다.
"""
from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from common.config import get_rate_limit_burst, get_rate_limit_rpm
from common.db import close_pool, init_pool
from common.rate_limit import RateLimitMiddleware

from app.modules.Agent_orchestrator import router as agent_orchestrator_router
from app.modules.TTS_V2.app.routers.tts_v2 import router as tts_v2_router
from app.modules.TTS_V2.app.routers.voice_profile_router import router as voice_profile_router
from app.modules.ChapterStudio_V1 import router as chapter_studio_router
from app.modules.ChapterStudio_V1.common.config import media_root_dir
from app.modules.ExamForge_V1 import router as exam_forge_router
from app.modules.OCR_v1 import health_router as ocr_health_router
from app.modules.OCR_v1 import ingest_router as ocr_ingest_router
from app.modules.OCR_v1 import search_router as ocr_search_router
from app.modules.Telegram_control_module import router as telegram_control_router
from app.modules.ASR_V1.app.routers.asr_v1 import router as asr_v1_router
from app.modules.Chat_V1.app.router import router as chat_v1_router
from app.modules.ChapterStudio_V1.app.routers.curriculum import router as curriculum_router
from app.modules.ChapterStudio_V1.app.routers.lessons import router as lessons_router
from app.modules.ChapterStudio_V1.app.routers.tutor_preview import router as tutor_preview_router
from app.modules.Chat_V1.app.spring_adapter import router as chat_spring_adapter_router
from app.modules.ExamForge_V1 import spring_adapter_router as mock_exam_adapter_router
from app.modules.ExamForge_V1 import mock_exam_analysis_router

_LOG = logging.getLogger(__name__)

# 프로덕션 여부 — ENVIRONMENT=production 일 때만 True
_is_production = os.getenv("ENVIRONMENT", "development").lower() == "production"

# FASTAPI_API_KEY 미설정 시 경고 (인증이 비활성화되기 때문에 운영 환경에서 위험)
if not os.getenv("FASTAPI_API_KEY"):
    _LOG.warning("FASTAPI_API_KEY 미설정 — API 인증이 비활성화 상태입니다")

# 인증 면제 경로 — /health 만 항상 면제, 문서 경로는 개발 편의상 추가
_HEALTH_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/media"}
_PUBLIC_PATH_PREFIXES = ("/media/",)

# CORS 허용 출처 결정 로직
# - CORS_ORIGINS 환경변수 설정 시: 쉼표 구분 값 사용
# - 미설정 + 프로덕션: 빈 목록 (교차 출처 전면 차단)
# - 미설정 + 개발: "*" (개발 편의상 전체 허용)
_cors_origins_raw = os.getenv("CORS_ORIGINS", "")
if _cors_origins_raw:
    _cors_origins = [o.strip() for o in _cors_origins_raw.split(",")]
elif _is_production:
    _cors_origins = []
else:
    _cors_origins = ["*"]


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """X-API-Key 헤더로 요청을 인증한다. 키 미설정 시 인증을 비활성화한다."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        api_key = os.getenv("FASTAPI_API_KEY")
        if api_key is None or _is_auth_exempt(request.url.path):
            return await call_next(request)
        provided = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(provided, api_key):
            return JSONResponse(
                status_code=401, content={"detail": "유효하지 않은 API 키"},
            )
        return await call_next(request)


def _is_auth_exempt(path: str) -> bool:
    """브라우저 오디오 요청은 헤더를 붙일 수 없으므로 media 경로를 공개한다."""
    return path in _HEALTH_PATHS or path.startswith(_PUBLIC_PATH_PREFIXES)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """앱 시작 시 DB 풀 생성, 종료 시 풀 해제."""
    await init_pool()
    yield
    await close_pool()


# 프로덕션에서는 Swagger/ReDoc/OpenAPI 스키마 엔드포인트를 비활성화한다
app = FastAPI(
    title="backend-fastapi",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

app.add_middleware(ApiKeyMiddleware)
# 속도 제한은 API 키 인증 이전에 적용 — 인증 전에 과부하를 차단한다
app.add_middleware(
    RateLimitMiddleware,
    rpm=get_rate_limit_rpm(),
    burst=get_rate_limit_burst(),
    exempt_paths=_HEALTH_PATHS,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_MEDIA_ROOT = media_root_dir()
_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_MEDIA_ROOT)), name="media")

app.include_router(agent_orchestrator_router)
app.include_router(telegram_control_router)
app.include_router(chapter_studio_router)
app.include_router(tts_v2_router, prefix="/api/tts-v2")
app.include_router(voice_profile_router, prefix="/api/tts-v2/voice-profiles")
app.include_router(exam_forge_router)
app.include_router(ocr_health_router, prefix="/api/ocr/v1")
app.include_router(ocr_ingest_router, prefix="/api/ocr/v1")
app.include_router(ocr_search_router, prefix="/api/ocr/v1")
app.include_router(asr_v1_router)
app.include_router(chat_v1_router)
app.include_router(curriculum_router)
app.include_router(lessons_router)
app.include_router(tutor_preview_router)
app.include_router(chat_spring_adapter_router)
app.include_router(mock_exam_adapter_router)
app.include_router(mock_exam_analysis_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "fastapi"}
