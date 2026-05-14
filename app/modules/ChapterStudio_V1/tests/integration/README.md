# tests/integration

## 모듈 목적
DB와 파이프라인을 포함한 통합 검증을 보관한다.

## IN·OUT
IN은 실제 또는 mock 인프라 입력이며 OUT은 통합 테스트 결과다.

## 환경변수
Phase 5 이후 `DATABASE_URL`, `DATABASE_SCHEMA`를 사용한다.

## 의존성
Phase 2 기준 해당 없음.

## 사용 예시
```bash
uv --cache-dir .uv-cache run pytest -v tests/integration/
```

## 에러 정책
인프라 연결 실패는 통합 테스트 실패로 보고한다.
