"""AssignmentGrader_V1 환경 설정 — .env 값을 한 곳에서만 읽는다."""

import os


def get_spring_base_url() -> str:
    """Spring Boot 베이스 URL — 기본값은 로컬 개발 포트."""
    # 환경변수 미설정 시 로컬 Spring 기본 포트 + context-path 사용
    return os.getenv("SPRING_BASE_URL", "http://localhost:8080/api").rstrip("/")


def get_internal_token() -> str:
    """Spring X-Internal-Token 헤더 값 — FastAPI → Spring 내부 인증에 사용한다."""
    # APP_INTERNAL_TOKEN 은 Spring application.yml 의 app.internal.token 과 동일한 값
    return os.getenv("APP_INTERNAL_TOKEN", "local-dev-token")


def get_grading_timeout_seconds() -> int:
    """텍스트 채점 Gemini 호출 타임아웃(초). 기본 90초."""
    return int(os.getenv("ASSIGNMENT_GRADER_TIMEOUT_SECONDS", "90"))


def get_spring_callback_timeout_seconds() -> int:
    """Spring 콜백 HTTP POST 타임아웃(초). 기본 10초."""
    return int(os.getenv("ASSIGNMENT_GRADER_CALLBACK_TIMEOUT_SECONDS", "10"))
