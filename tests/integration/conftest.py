"""통합 테스트 공통 픽스처 — 실제 FastAPI 앱에 HTTP 요청을 보내는 클라이언트를 제공한다.

mock, MagicMock, @patch, monkeypatch 절대 금지.
스프링이 실제로 보내는 것과 동일한 JSON 페이로드를 사용한다.
"""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from common.rate_limit import RateLimitMiddleware
from main import app


def _get_rate_limiter() -> RateLimitMiddleware | None:
    """미들웨어 스택에서 RateLimitMiddleware 인스턴스를 탐색해 반환한다.

    미들웨어 스택은 첫 ASGI 호출 이후에만 구성되므로,
    클라이언트 픽스처 진입 후에 호출해야 한다.
    스택 구조: ServerErrorMiddleware → CORSMiddleware → RateLimitMiddleware → ...
    """
    stack = app.middleware_stack
    if stack is None:
        return None
    # CORS 레이어 건너뛰기
    cors_layer = getattr(stack, "app", None)
    if cors_layer is None:
        return None
    rate_layer = getattr(cors_layer, "app", None)
    if isinstance(rate_layer, RateLimitMiddleware):
        return rate_layer
    return None


def _get_test_api_key() -> str:
    """루트 conftest.py가 설정한 테스트 API 키를 읽는다.

    FASTAPI_API_KEY 환경변수가 없으면 빈 문자열을 반환해
    ApiKeyMiddleware가 인증 자체를 비활성화하도록 한다.
    """
    return os.environ.get("FASTAPI_API_KEY", "")


@pytest.fixture
async def client() -> AsyncClient:
    """실제 FastAPI 앱을 ASGI 트랜스포트로 감싸 HTTP 클라이언트를 반환한다.

    외부 서비스(Qdrant, Modal, Anthropic)에 실제로 연결하지 않으며,
    FastAPI 레이어의 라우팅·스키마 검증·응답 구조만 검증한다.

    ApiKeyMiddleware를 정상 통과할 수 있도록 X-API-Key 헤더를 기본 포함한다.
    루트 conftest.py가 FASTAPI_API_KEY 환경변수를 설정했으므로
    테스트 키로 실제 인증 경로를 통과한다 (보안 자체를 끄지 않음).

    각 테스트 시작 시 RateLimitMiddleware 버킷을 초기화해
    이전 테스트의 토큰 소비가 다음 테스트에 누적되지 않도록 한다.
    """
    api_key = _get_test_api_key()
    # 실제 미들웨어 인증 경로를 통과하는 헤더 — 보안 우회가 아닌 정상 인증이다
    auth_headers = {"X-API-Key": api_key} if api_key else {}

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=auth_headers,
    ) as c:
        # 미들웨어 스택은 첫 요청 이후 구성 — 더미 요청으로 스택을 초기화한다
        await c.get("/health")
        limiter = _get_rate_limiter()
        if limiter is not None:
            # 이전 테스트에서 소비된 토큰을 리셋해 429 연쇄 실패를 방지
            limiter.reset_buckets()
        yield c
