# pipeline

## 모듈 목적
ChapterStudioState와 계층 간 변환을 관리한다.

## IN·OUT
IN은 `ChapterRequest`와 노드별 State 조각이며 OUT은 `ChapterStudioState`, `ChapterResponse`, DB 행 묶음이다.

## 노드 순서
`prepare_context → generate_lesson → content_verify → postprocess_slides`.
- `generate_lesson`: 강의 JSON 생성 + 형식 self-check/repair(분량·구조) 후 payload를 `lesson_payload`에 stash한다.
- `content_verify`: 사실·논리 오류를 LLM 1회 검증→교정→1회 재검증한다(graceful). 다운스트림 records(slides·quiz_set·voice_scripts 등)를 단 한 번 emit한다.

## 환경변수
- `CHAPTERSTUDIO_CONTENT_VERIFY` (기본 ON): 내용 정확성 검증 패스 ON/OFF.
- `ACTIVE_VERIFIER_MODEL` (선택): 검증 전용 커넥터. 미설정 시 `ACTIVE_TEXT_MODEL`을 그대로 쓴다.
- 그 외 환경값은 `common.config`가 관리한다.

## 의존성
`schemas`, `common.errors`에 의존한다.

## 사용 예시
```python
from pipeline.converters import request_to_initial_state
```

## 에러 정책
변환 실패는 `ConversionError`로 올린다.
