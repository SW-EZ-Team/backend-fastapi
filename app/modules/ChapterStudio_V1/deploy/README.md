# deploy

## 모듈 목적
Modal 배포 스크립트를 보관한다.

## IN·OUT
IN은 Modal secret과 모델 설정이며 OUT은 Modal endpoint다.

## 환경변수
Phase 7에서 `ANTHROPIC_API_KEY`, `DATABASE_URL`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`를 사용한다.

## 의존성
`modal`에 의존한다.

## 사용 예시
```bash
modal deploy deploy/modal_app.py
```

## 에러 정책
배포 실패는 Phase 7 BLOCKED로 보고한다.
