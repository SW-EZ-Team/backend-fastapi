# SW-EZ-Team backend-fastapi 서비스 컨테이너
# uv로 의존성 설치 후 slim 런타임으로 분리한다
# api / celery worker / celery beat 모두 이 이미지를 공유한다

# ──────────────────────────────────────────
# Stage 1: uv로 의존성 설치
# ──────────────────────────────────────────
FROM python:3.12-slim-bookworm AS deps

# uv 공식 이미지에서 바이너리만 복사
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

WORKDIR /app

# bind mount가 아니라 copy 기반 링크(Docker 레이어 호환)
ENV UV_LINK_MODE=copy

# 의존성 명세만 먼저 복사해서 캐시 활용
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ──────────────────────────────────────────
# Stage 2: 런타임
# ──────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

# 네트워크/SSL + 오디오 처리 최소 런타임 라이브러리
# libsndfile1: soundfile/librosa 패키지의 네이티브 공유 라이브러리 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# 권한 없는 전용 사용자 생성 (보안 강화)
RUN useradd -r -u 1001 appuser

WORKDIR /app

# deps 스테이지에서 만든 venv 복사
COPY --from=deps /app/.venv /app/.venv

# 애플리케이션 소스 전체 복사
COPY . /app

RUN chown -R appuser:appuser /app

# venv의 bin을 PATH에 추가 + 파이썬 런타임 튜닝
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

EXPOSE 8000

# 기본 커맨드는 api 서버 — compose에서 worker/beat용으로 override 한다
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
