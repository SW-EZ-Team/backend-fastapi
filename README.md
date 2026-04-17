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

## 텔레그램 봇

운영 봇 주소: **https://t.me/ilgwa_EZ_Team_bot**

### 사용자 연동 방법

1. 유저가 위 봇에 아무 메시지나 보내면 FastAPI `app/telegram/` 웹훅이 수신한다.
2. 웹훅 페이로드에서 `chat.id`를 추출해 해당 유저의 `telegram_account.telegram_chat_id`에 저장한다.
3. 이후 과제 알림·AI 튜터 캡션은 이 `chat_id`로 발송된다.

### 자동 승인 로직

- 신규 `chat_id` 수신 시 어떤 유저에게 귀속시킬지, 인증 코드·전화번호 매칭·수동 승인 등 **자동 승인 방식은 추후 확정**한다.
- 확정 방식과 무관하게 **승인 로직 자체는 전부 FastAPI 안에서 처리**한다. Spring·Rust는 관여하지 않는다.

**개념 스케치 (미확정)**: 귀속되지 않은 신규 chat_id는 `telegram_account_pending` 임시 테이블 또는 Redis 큐에 일시 적재한 뒤, 관리자 승인 또는 자동 매칭 로직(인증 코드·전화번호 비교 등)이 최종 유저에 귀속시키는 방식을 상정한다. 이 흐름은 개념 스케치이며, 실제 적재 방식·테이블 스키마·매칭 알고리즘은 FastAPI 담당자가 확정한다.

### ⚠️ 보안 주의

- **봇 토큰 평문 하드코딩 절대 금지**. 토큰은 환경변수 또는 `admin_telegram_credential` 테이블(슈퍼 관리자 페이지 F16.3)에서 관리한다.

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
| [lib-rust](https://github.com/SW-EZ-Team/lib-rust) | OCR 전처리 PyO3 Rust 라이브러리 (wheel) |
| [infra](https://github.com/SW-EZ-Team/infra) | 로컬 DB 서버 묶음 (PostgreSQL·Redis·Qdrant) |

---

## 모듈 설계 원칙 (라이브러리형 모듈)

각 AI 파이프라인 단계는 `app/modules/<ModuleName>/`에 **독립된 라이브러리형 모듈**로 분리한다. 라우터·Celery task·다른 모듈은 `from app.modules.<ModuleName> import ...` 형태로 가져와 사용한다.

### 구조

```
app/modules/<ModuleName>/
├── __init__.py        공개 API만 re-export
├── config.py          상수·프롬프트·파라미터
├── <core>.py          핵심 로직
├── model_loader.py    (AI 모듈 한정) 싱글톤 모델 로더
├── fallback.py        (선택) 폴백 구현
├── validator.py       (선택) 출력 검증
├── README.md          모듈 사용법·내부 구조
└── tests/             모듈 단위 테스트
```

### 규칙

- **공개 API는 `__init__.py`에서만 정의**한다. 외부는 항상 `from app.modules.X import func` 만 쓴다. 내부 파일을 직접 import 금지.
- **모듈 간 직접 import 금지**. 공통 기능이 필요하면 `app/core/`로 승격한다.
- **무거운 리소스(LLM·ASR·OCR 모델)는 싱글톤 로더**로 lazy-load 한다. Celery 워커 프로세스당 1회만 로드.
- **모듈별 README**: 사용법·IN/OUT·파라미터·폴백 정책을 명시한다.
- **테스트는 모듈 내부 `tests/`**에 둔다. 모듈이 자기 자신을 검증할 수 있어야 한다.

### 현재 등록된 모듈

| 모듈 | 역할 | 상태 |
|---|---|---|
| `AI_CPU_Kanana_Nano_Q4` | 텔레그램 과제 캡션 생성 (CPU-only, Kanana Nano 2.1B Q4_K_M) | ✅ |
| `FilePreprocessor` | 오피스 문서(.docx/.pptx/.xlsx) → Markdown 변환 (MarkItDown) | 📋 계획 (설계 확정, 구현 예정) |
