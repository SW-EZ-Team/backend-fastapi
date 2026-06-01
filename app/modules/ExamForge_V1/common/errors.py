"""ExamForge 모듈 공통 예외 정의."""
from __future__ import annotations


class ExamForgeError(Exception):
    """모듈 기본 예외."""


class PipelineError(ExamForgeError):
    """파이프라인 실행 중 복구 불가 오류."""


class ValidationError(ExamForgeError):
    """문제 검증 실패."""


class TemplateNotFoundError(ExamForgeError):
    """등록되지 않은 템플릿 ID."""


class GenerationError(ExamForgeError):
    """AI 문제 생성 실패."""


class ParseError(ExamForgeError):
    """AI 응답 파싱 실패."""


class BudgetExceededError(ExamForgeError):
    """LLM 호출 예산 초과 — 서킷 브레이커 발동."""


class ConnectorError(ExamForgeError, RuntimeError):
    """AI 커넥터 공통 오류."""


class AuthError(ConnectorError):
    """API 키 누락 또는 인증 실패."""


class RateLimitError(ConnectorError):
    """벤더 API 요청 한도 초과."""


class TimeoutError(ConnectorError):
    """벤더 응답 타임아웃 또는 일시 장애."""


class ContextLengthExceeded(ConnectorError):
    """입력 길이가 모델 컨텍스트 한도를 초과."""
