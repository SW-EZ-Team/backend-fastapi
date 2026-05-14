# ChapterStudio_V1

FastAPI 기반 AI 챕터 생성 모듈의 sandbox 구현 공간이다. 구현은 이 폴더에서 검증한 뒤, 사용자가 별도로 지시할 때만 `backend-fastapi/`로 이관한다.

## 모듈 목적
챕터 단위 슬라이드, 퀴즈, 노트, 과제, 음성 대본 생성을 하나의 library-style FastAPI 모듈로 제공한다.

## IN·OUT
IN은 `ChapterRequest`와 HTTP 요청이며 OUT은 `ChapterResponse`, DB 행 묶음, `/healthz` 응답이다.

## 환경변수
`DATABASE_URL`, `DATABASE_SCHEMA`, `LOG_LEVEL`, `ACTIVE_TEXT_MODEL`, `ACTIVE_PLANNER_MODEL`, `ACTIVE_TTS_MODEL`, `ANTHROPIC_API_KEY`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `TTS_ENDPOINT`를 사용한다.

## 의존성
`app`, `pipeline`, `schemas`, `db`, `common`, `infra/schema/migrations/V2__chapter_studio.sql`에 의존한다.

## 사용 예시
```bash
uv --cache-dir .uv-cache run uvicorn app.main:app --port 8800
```

## 에러 정책
입력 검증 실패는 Pydantic 오류로, 변환 실패는 `ConversionError`로, DB ping 실패는 `/healthz` 503으로 보고한다.

## 인프라 사용 정책

- **DB**: PostgreSQL 17 (`infra/docker-compose.yml`의 `sw-ez-postgres`). schema = `chapter_studio`.
- **마이그레이션**: Flyway (`infra/schema/migrations/V*__*.sql`). ChapterStudio_V1 자체 마이그레이션 보유 금지.
- **redis**: 사용 안 함. infra에 떠 있어도 ChapterStudio_V1은 연결하지 않는다.
- **qdrant**: 사용 안 함. infra에 떠 있어도 ChapterStudio_V1은 연결하지 않는다.
- **앱 런타임**: uv venv. Docker 미사용. Mac MPS GPU 접근과 빠른 sandbox 반복 실행을 위함.
- **포트**: FastAPI 8800.

## 실행

```bash
cd infra
./scripts/dev-up.sh

cd ../Test_FastAPI_Module/ChapterStudio_V1
uv --cache-dir .uv-cache run uvicorn app.main:app --port 8800
```

## 헬스체크

```bash
curl http://localhost:8800/healthz
```

Phase 1 기준 응답은 `{"status":"ok","db":"ok","modal":"skipped"}`다. Modal 실제 ping은 Phase 7에서 추가한다.
