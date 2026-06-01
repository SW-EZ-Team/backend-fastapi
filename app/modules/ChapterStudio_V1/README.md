# ChapterStudio_V1

FastAPI 기반 AI 챕터 생성 모듈의 sandbox 구현 공간이다. 구현은 이 폴더에서 검증한 뒤, 사용자가 별도로 지시할 때만 `backend-fastapi/`로 이관한다.

## 모듈 목적

챕터 단위 슬라이드, 퀴즈, 노트, 과제, 음성 대본 생성을 하나의 library-style FastAPI 모듈로 제공한다.

## IN·OUT

IN은 `ChapterRequest`와 HTTP 요청이며 OUT은 `ChapterResponse`, DB 행 묶음, `/healthz` 응답이다.

## 환경변수

| 변수명 | 필수 | 기본값 | 설명 |
|--------|------|--------|------|
| `DATABASE_URL` | 필수 | — | PostgreSQL 연결 문자열 |
| `DATABASE_SCHEMA` | 선택 | `chapter_studio` | DB 스키마명 |
| `LOG_LEVEL` | 선택 | `INFO` | 로그 출력 레벨 |
| `ACTIVE_TEXT_MODEL` | 선택 | `qwen27b_modal` | 강의 생성에 쓸 커넥터 이름 |
| `ACTIVE_PLANNER_MODEL` | 선택 | `opus46` | 커리큘럼 계획에 쓸 커넥터 이름 |
| `ACTIVE_TTS_MODEL` | 선택 | `tts_v1` | TTS 커넥터 이름 |
| `ACTIVE_VERIFIER_MODEL` | 선택 | — | 내용 정확성 검증 전용 커넥터. 미설정 시 `ACTIVE_TEXT_MODEL` 폴백 |
| `CHAPTERSTUDIO_LESSON_SELF_REPAIR` | 선택 | `true` | 강의 생성 후 분량·형식 self-check + targeted-repair 활성화. `false`로 끄면 수정 없이 다음 단계로 넘어간다 |
| `CHAPTERSTUDIO_CONTENT_VERIFY` | 선택 | `true` | 내용 정확성(사실·논리 오류) 검증 패스 활성화. `false`로 끄면 생성된 강의를 그대로 후처리로 넘긴다 |
| `ANTHROPIC_API_KEY` | 조건부 | — | Claude 커넥터 사용 시 필요 |
| `MODAL_TOKEN_ID` | 조건부 | — | Modal GPU 배포 시 필요 |
| `MODAL_TOKEN_SECRET` | 조건부 | — | Modal GPU 배포 시 필요 |
| `TTS_ENDPOINT` | 조건부 | — | TTS 서비스 엔드포인트 |

## 의존성

`app`, `pipeline`, `schemas`, `db`, `common`, `infra/schema/migrations/V2__chapter_studio.sql`에 의존한다.

공통 유틸 `common/llm_output.py`의 `strip_thinking`·`extract_json_block`·`loads_lenient`를 파이프라인 전반에서 사용한다. 모델이 codex·Qwen·Claude 어느 것으로 스왑되어도 `<think>` 블록과 마크다운 펜스를 일관되게 정규화한다. 자세한 내용은 `common/llm_output.py` 참조.

## 파이프라인 구조

```
prepare_context
      │
      ▼
generate_lesson  ← ACTIVE_TEXT_MODEL 호출 + 분량·형식 self-check/repair
      │            (CHAPTERSTUDIO_LESSON_SELF_REPAIR=false면 repair 생략)
      │
      ▼
content_verify   ← 사실·논리 오류 검증(1회) → 교정(1회) → 재검증(1회)
      │            (CHAPTERSTUDIO_CONTENT_VERIFY=false면 이 단계 생략)
      │            검증/교정 커넥터: ACTIVE_VERIFIER_MODEL (미설정 시 ACTIVE_TEXT_MODEL 폴백)
      │
      ▼
postprocess_slides  ← DB records(slides·quiz_set·voice_scripts 등) emit
      │
      ▼
     END
```

### 각 단계 설명

- **`prepare_context`**: 챕터 요청·커리큘럼 정보를 파이프라인 상태로 변환한다. 커리큘럼 생성은 이 단계 이전에 별도 완료된 상태로 들어온다(커리큘럼 생성 자체는 파이프라인 내부에 없고 변경되지 않는다)
- **`generate_lesson`**: `ACTIVE_TEXT_MODEL` 커넥터로 강의 JSON을 생성한다. 생성 직후 `pipeline/quality.py`로 분량·형식을 self-check하고, 미달 항목이 있으면 `pipeline/repair.py`의 targeted-repair로 1회 보강한다. 결과는 `lesson_payload`에 stash해 다음 노드로 넘긴다
- **`content_verify`**: `lesson_payload`의 사실·논리 오류를 LLM 1회 검증한다. 명백한 오류가 검출되면 1회 교정하고, 교정 후 1회 재검증한다. 인덱스 계약(slide_idx 집합)이 깨지면 원본으로 되돌린다. `ACTIVE_VERIFIER_MODEL`이 미설정이면 `ACTIVE_TEXT_MODEL`과 동일 커넥터를 쓴다. 전 단계가 실패해도 graceful로 원본을 유지하며 절대 예외로 죽지 않는다
- **`postprocess_slides`**: 검증·교정을 거친 payload를 DB records(slides, quiz_set, voice_scripts 등)로 단 한 번 emit한다

### 견고성 장치

- 모든 노드에서 parsing 실패·검증 실패 시 원본 유지(graceful). 예외로 파이프라인이 죽지 않는다
- `strip_thinking` 적용으로 모델 스왑 시에도 `<think>` reasoning이 강의 본문에 섞이지 않는다
- content_verify의 교정은 검증기가 "명백한 오류"로 지목한 것만 손댄다. 오탐 방지를 위해 확신이 낮으면 원본 유지
- slide_idx·키 계약은 불변. 교정 병합 후 인덱스가 깨지면 즉시 원본으로 되돌린다

## 사용 예시

```bash
uv --cache-dir .uv-cache run uvicorn app.main:app --port 8800
```

## 에러 정책

입력 검증 실패는 Pydantic 오류로, 변환 실패는 `ConversionError`로, DB ping 실패는 `/healthz` 503으로 보고한다.

## 인프라 사용 정책

- **DB**: PostgreSQL 17 (`infra/docker-compose.yml`의 `sw-ez-postgres`). schema = `chapter_studio`
- **마이그레이션**: Flyway (`infra/schema/migrations/V*__*.sql`). ChapterStudio_V1 자체 마이그레이션 보유 금지
- **redis**: 사용 안 함. infra에 떠 있어도 ChapterStudio_V1은 연결하지 않는다
- **qdrant**: 사용 안 함. infra에 떠 있어도 ChapterStudio_V1은 연결하지 않는다
- **앱 런타임**: uv venv. Docker 미사용. Mac MPS GPU 접근과 빠른 sandbox 반복 실행을 위함
- **포트**: FastAPI 8800

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
