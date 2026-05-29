"""API 키 기반 토큰 버킷 속도 제한 미들웨어.

각 API 키(또는 클라이언트 IP)에 독립적인 토큰 버킷을 할당한다.
버킷은 .env의 RATE_LIMIT_RPM(분당 요청수)·RATE_LIMIT_BURST(순간 허용량) 로 구성된다.
asyncio.Lock으로 버킷 상태를 스레드 안전하게 갱신한다.
"""
from __future__ import annotations

import asyncio
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# 버킷 상태 타입 별칭 — (현재 토큰 수, 마지막 리필 시각)
_BucketState = tuple[float, float]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """API 키 기반 토큰 버킷 속도 제한 미들웨어.

    요청마다 X-API-Key 헤더(없으면 클라이언트 IP)를 키로 사용한다.
    exempt_paths에 속하는 경로(헬스체크·docs 등)는 제한 없이 통과된다.
    """

    def __init__(
        self,
        app,
        rpm: int = 60,
        burst: int = 10,
        exempt_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        # 분당 리필 속도를 초당 속도로 변환 — 버킷 계산 단위 통일
        self._refill_rate: float = rpm / 60.0
        self._burst: float = float(burst)
        self._exempt: set[str] = exempt_paths or set()
        # 키별 버킷 상태 딕셔너리 — {키: (토큰, 마지막_리필_시각)}
        self._buckets: dict[str, _BucketState] = {}
        # 버킷 전체를 보호하는 단일 락 — 키별 세분화 대신 단순성을 우선
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """요청을 가로채 속도 제한 여부를 판단한다."""
        # 면제 경로는 버킷을 소비하지 않고 즉시 통과
        if request.url.path in self._exempt:
            return await call_next(request)

        # API 키 우선 — 없으면 클라이언트 IP로 폴백
        key = request.headers.get("X-API-Key") or (
            request.client.host if request.client else "unknown"
        )
        allowed = await self._try_consume(key)
        if not allowed:
            # 429 응답: Retry-After 헤더로 재시도 권장 시간을 알린다
            return JSONResponse(
                status_code=429,
                content={"detail": "요청 속도 제한을 초과했습니다. 잠시 후 다시 시도하세요."},
                headers={"Retry-After": "60"},
            )
        return await call_next(request)

    def reset_buckets(self) -> None:
        """모든 버킷 상태를 초기화한다.

        테스트 픽스처에서 각 테스트 간 누적된 토큰 소비를 리셋할 때 사용한다.
        프로덕션 코드에서는 호출하지 않는다.
        """
        self._buckets.clear()

    async def _try_consume(self, key: str) -> bool:
        """토큰 버킷에서 토큰 1개를 소비하려 시도한다.

        토큰이 충분하면 True를 반환하고 버킷을 갱신한다.
        토큰이 부족하면 False를 반환한다.
        """
        now = time.monotonic()
        async with self._lock:
            tokens, last_refill = self._buckets.get(key, (self._burst, now))
            # 마지막 리필 이후 경과 시간만큼 토큰을 보충 — 버스트 상한 적용
            elapsed = now - last_refill
            tokens = min(self._burst, tokens + elapsed * self._refill_rate)

            if tokens < 1.0:
                # 토큰 부족 — 버킷은 갱신하되 소비하지 않음
                self._buckets[key] = (tokens, now)
                return False

            # 토큰 1개 소비 후 버킷 상태 저장
            self._buckets[key] = (tokens - 1.0, now)
            return True
