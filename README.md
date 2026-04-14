# backend-fastapi

AI 사용 및 AI 에이전트 사용 전담 서버다.

---

## 역할 및 책임 범위

LLM·GPU 추론·OCR 추론·RAG·AI 에이전트를 모두 여기서 처리한다. Celery 워커로 비동기 AI 작업을 큐잉한다.

| 구분 | 내용 |
|---|---|
| LLM 호출 | Claude API (검증 ↔ 재작업 루프) |
| GPU 추론 | Modal 서버리스 (Qwen / GLM / TTS / ASR / ForcedAligner / PersonaPlex / Tesseract) |
| OCR 추론 | PaddleOCR ONNX (Rust로부터 gRPC 수신) |
| 벡터 검색 | Qdrant RAG |
| 비동기 큐 | Celery 5.4.0 + Redis |
| AI 에이전트 | 워크플로 오케스트레이션 (추후 확장) |

---

## 하지 않는 것

- 메인 비즈니스 로직·결제·인증·세션 처리 안 함 (Spring의 책임)
- PDF/이미지 전처리 안 함 (Rust의 책임)
- SSE 스트리밍 안 함 (프로젝트 전체에서 SSE 미사용)

---

## 기술 스택

| 항목 | 버전 |
|---|---|
| Language | Python 3.12 |
| Framework | FastAPI 0.115.5 |
| 의존성 관리 | uv |
| 비동기 큐 | Celery 5.4.0 |
| Cache / 브로커 | Redis 5.2.0 |
| OCR | PaddleOCR ONNX |
| 벡터 DB | Qdrant |

---

## 데이터 플로우

```
Spring Boot → FastAPI (AI·채점 요청)
Rust         → FastAPI (OCR gRPC)
FastAPI      → Modal GPU / Claude API / Qdrant
```

---

## 로컬 실행

```bash
# 의존성 설치 (uv 사용)
uv sync

# 개발 서버 실행
uv run uvicorn main:app --reload

# Celery 워커 실행
uv run celery -A app.worker worker --loglevel=info
```

DB 등 의존 서비스는 infra 레포의 docker-compose로 먼저 기동한다.

---

## 관련 저장소

| 레포 | 역할 |
|---|---|
| [backend-spring](https://github.com/SW-EZ-Team/backend-spring) | 메인 백엔드 (REST API·비즈니스 로직·인증·결제) |
| [backend-rust](https://github.com/SW-EZ-Team/backend-rust) | PDF/이미지 전처리 + 오케스트레이션 |
| [infra](https://github.com/SW-EZ-Team/infra) | 로컬 DB 서버 묶음 (PostgreSQL·Redis·Qdrant) |
