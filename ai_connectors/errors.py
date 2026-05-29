"""AI 커넥터 공통 예외 계층.

벤더별 커넥터는 자사 SDK 예외를 여기 클래스로 번역해 올린다.
이렇게 해야 app/main.py의 핸들러 한 벌로 HTTP 상태코드를 매핑할 수 있다.
"""
from __future__ import annotations


class AIConnectorError(Exception):
    """AI 커넥터 공통 최상위 예외."""


class AuthError(AIConnectorError):
    """API 키 누락/무효 — 401."""


class RateLimitError(AIConnectorError):
    """요청 한도 초과 — 429."""


class ModelNotFoundError(AIConnectorError):
    """모델 미등록/오타 — 503."""


class ModelLoadError(AIConnectorError):
    """모델 가중치 로드 실패 — 503.

    파일 누락, bf16 역직렬화 실패, MLX 메모리 부족 등.
    """


class InferenceError(AIConnectorError):
    """추론 중 실패 — 502.

    모델은 로드되었으나 generate() 호출에서 벤더 SDK가 오류를 던진 경우.
    """


class TimeoutError(AIConnectorError):
    """벤더 응답 타임아웃 — 504.

    참고: 파이썬 내장 TimeoutError와 이름 충돌하므로 import 시 alias 권장
    (예: `from ai_connectors.errors import TimeoutError as ConnectorTimeoutError`).
    """


# --- 텍스트 커넥터 공통 예외 계층 (ChapterStudio 스키마 호환) ---

# AIConnectorError 의 alias — 샌드박스 코드와 import 경로를 일치시켜
# production 마이그레이션 시 수정 범위를 최소화한다.
ConnectorError = AIConnectorError


class ContextLengthExceeded(AIConnectorError):
    """입력 토큰이 모델 최대 컨텍스트를 초과 — 413."""
